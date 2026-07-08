# Copyright 2019-2025 SURF.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Aruba Central client using MSP token exchange (RFC 8693).

Uses a single set of MSP credentials to obtain tenant-scoped access tokens,
eliminating the need for per-tenant client_id/client_secret pairs.

Workspace IDs for each tenant are resolved dynamically by querying the
HPE GreenLake workspace management API (``/workspaces/v1/msp-tenants``).
The ``customer_name`` is matched against the GreenLake workspace names
(case-insensitive exact match); an unknown customer fails at resolution.

Configuration is read from ``ARUBA_*`` environment variables via
:class:`~aruba_client.config.ArubaConfig`, or callers can pass an explicit
``config`` object to :func:`get_central_client` / :func:`get_msp_tenant_names`.
"""

import time
from collections.abc import Callable, Iterator
from http import HTTPStatus
from typing import Any

import httpx
import structlog
from pycentral import NewCentralBase
from pycentral.new_monitoring import MonitoringAPs, MonitoringSites
from pycentral.new_monitoring.constants import AP_LIMIT, SITE_LIMIT

from aruba_client.config import ArubaConfig
from aruba_client.schema import AccessPoint, CentralResponse, SiteConfig, SiteRegistry

logger = structlog.get_logger(__name__)

GREENLAKE_MSP_TENANTS_URL = "https://global.api.greenlake.hpe.com/workspaces/v1/msp-tenants"

_msp_token_cache: dict[str, tuple[str, float]] = {}
_workspace_cache: dict[str, str] = {}  # workspace_name (upper) -> workspace_id (hex)
_workspace_cache_expiry: float = 0.0
_WORKSPACE_CACHE_TTL: int = 3600
_DEFAULT_TOKEN_TTL: int = 7200
_TOKEN_EXPIRY_BUFFER: int = 300

# Retry settings for the GreenLake token/tenant calls below. pycentral's
# NewCentralBase.command() already retries Central API calls (incl. 429), but
# these GreenLake OAuth/workspace calls go through plain httpx, so we mirror the
# SDK's exponential backoff here. Values match pycentral.base.RETRY_* defaults.
_RETRY_MAX_ATTEMPTS: int = 3
_RETRY_INITIAL_BACKOFF: float = 1.0
_RETRY_BACKOFF_MULTIPLIER: float = 2.0
_RETRY_MAX_BACKOFF: float = 10.0
_RETRY_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


class ArubaClientError(Exception):
    pass


def _request_with_retry(method: str, url: str, *, context: str, **kwargs: Any) -> httpx.Response:
    """Issue an httpx request with retry on transient failures.

    Retries on transport errors (connection/timeout) and retryable status codes
    (429 + 5xx) with exponential backoff, then returns the final response so the
    caller can apply its own status-specific error handling. Non-retryable
    responses (e.g. 401/400) are returned immediately on the first attempt.
    """
    backoff = _RETRY_INITIAL_BACKOFF
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        is_last = attempt == _RETRY_MAX_ATTEMPTS
        try:
            with httpx.Client(http2=True) as client:
                response = client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            if is_last:
                raise ArubaClientError(f"{context} failed after {attempt} attempts: {exc}") from exc
            logger.warning(
                "Retrying after transport error",
                context=context,
                attempt=attempt,
                error=str(exc),
                backoff=backoff,
            )
        else:
            if is_last or response.status_code not in _RETRY_STATUS_CODES:
                return response
            logger.warning(
                "Retrying after retryable status",
                context=context,
                attempt=attempt,
                status_code=response.status_code,
                backoff=backoff,
            )
        time.sleep(backoff)
        backoff = min(backoff * _RETRY_BACKOFF_MULTIPLIER, _RETRY_MAX_BACKOFF)

    # Unreachable: the final attempt always returns or raises above.
    raise ArubaClientError(f"{context}: retries exhausted")


def _get_msp_token(client_id: str, client_secret: str, msp_workspace_id: str, oauth_url: str) -> str:
    """Obtain an MSP access token via client_credentials grant.

    Caches the token for 55 minutes (tokens are typically valid for 2 hours).
    """
    cache_key = f"{client_id}:{msp_workspace_id}"
    cached = _msp_token_cache.get(cache_key)
    if cached and cached[1] > time.time():
        logger.info("Using cached MSP token")
        return cached[0]

    token_url = f"{oauth_url}/{msp_workspace_id}/token"
    logger.info("Fetching MSP token", token_url=token_url)

    response = _request_with_retry(
        "POST",
        token_url,
        context="MSP token request",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if response.status_code != HTTPStatus.OK:
        raise ArubaClientError(f"MSP token request failed ({response.status_code}): {response.text}")

    token_data = response.json()
    access_token = token_data["access_token"]
    expires_in = token_data.get("expires_in", _DEFAULT_TOKEN_TTL)
    _msp_token_cache[cache_key] = (access_token, time.time() + expires_in - _TOKEN_EXPIRY_BUFFER)

    logger.info("MSP token obtained", expires_in=expires_in)
    return access_token


def _fetch_msp_tenants(msp_token: str) -> dict[str, str]:
    """Query HPE GreenLake to build a workspace_name -> workspace_id mapping for all MSP-managed tenants."""
    logger.info("Fetching MSP tenant workspace mappings", url=GREENLAKE_MSP_TENANTS_URL)

    response = _request_with_retry(
        "GET",
        GREENLAKE_MSP_TENANTS_URL,
        context="MSP tenants fetch",
        headers={"Authorization": f"Bearer {msp_token}", "Accept": "application/json"},
    )

    if response.status_code != HTTPStatus.OK:
        raise ArubaClientError(f"Failed to fetch MSP tenants ({response.status_code}): {response.text}")

    data = response.json()
    mapping = {
        name.upper(): wid
        for tenant in data.get("items", [])
        if (name := tenant.get("workspaceName", "")) and (wid := tenant.get("id", "").replace("-", ""))
    }

    logger.info("MSP tenant mappings fetched", count=len(mapping), tenants=sorted(mapping.keys()))
    return mapping


def _resolve_workspace_id(msp_token: str, customer_name: str) -> str:
    """Resolve a customer name to a GreenLake workspace ID, with caching."""
    global _workspace_cache, _workspace_cache_expiry

    key = customer_name.upper()

    if _workspace_cache and _workspace_cache_expiry > time.time():
        if wid := _workspace_cache.get(key):
            logger.info("Workspace ID from cache", customer=key, workspace_id=wid)
            return wid

    _workspace_cache = _fetch_msp_tenants(msp_token)
    _workspace_cache_expiry = time.time() + _WORKSPACE_CACHE_TTL

    wid = _workspace_cache.get(key)
    if not wid:
        raise ArubaClientError(
            f"Customer '{customer_name}' not found among MSP-managed tenants. "
            f"Known tenants: {sorted(_workspace_cache.keys())}"
        )
    return wid


def _exchange_for_tenant_token(msp_token: str, tenant_workspace_id: str, oauth_url: str) -> str:
    """Exchange an MSP token for a tenant-scoped access token (RFC 8693)."""
    token_url = f"{oauth_url}/{tenant_workspace_id}/token"
    logger.info("Exchanging MSP token for tenant token", tenant_workspace_id=tenant_workspace_id)

    response = _request_with_retry(
        "POST",
        token_url,
        context="Tenant token exchange",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": msp_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if response.status_code != HTTPStatus.OK:
        raise ArubaClientError(f"Tenant token exchange failed ({response.status_code}): {response.text}")

    token_data = response.json()
    logger.info("Tenant token obtained", expires_in=token_data.get("expires_in"))
    return token_data["access_token"]


def get_central_client(customer_name: str, *, config: ArubaConfig | None = None) -> NewCentralBase:
    """Create a NewCentralBase client for a tenant using MSP token exchange.

    Resolves ``customer_name`` to a GreenLake workspace ID by querying the
    HPE MSP tenants API, then exchanges the MSP token for a tenant-scoped
    access token via RFC 8693.

    If ``config`` is not provided, configuration is read from ``ARUBA_*`` environment variables.
    """
    if config is None:
        config = ArubaConfig()

    msp_client_id = config.MSP_CLIENT_ID.get_secret_value()
    msp_client_secret = config.MSP_CLIENT_SECRET.get_secret_value()
    msp_workspace_id = config.MSP_WORKSPACE_ID.get_secret_value()

    if not all([msp_client_id, msp_client_secret, msp_workspace_id]):
        raise ArubaClientError(
            "Missing MSP settings: ARUBA_MSP_CLIENT_ID, ARUBA_MSP_CLIENT_SECRET, ARUBA_MSP_WORKSPACE_ID"
        )

    msp_token = _get_msp_token(msp_client_id, msp_client_secret, msp_workspace_id, config.GREENLAKE_OAUTH_URL)
    tenant_workspace_id = _resolve_workspace_id(msp_token, customer_name)
    tenant_token = _exchange_for_tenant_token(msp_token, tenant_workspace_id, config.GREENLAKE_OAUTH_URL)

    return NewCentralBase(
        token_info={
            "new_central": {
                "base_url": config.BASE_URL,
                "access_token": tenant_token,
            }
        }
    )


def get_msp_tenant_names(*, config: ArubaConfig | None = None) -> list[str]:
    """Return the (upper-cased) workspace/tenant names of all MSP-managed Aruba tenants (live).

    If ``config`` is not provided, configuration is read from ``ARUBA_*`` environment variables.
    """
    if config is None:
        config = ArubaConfig()

    msp_client_id = config.MSP_CLIENT_ID.get_secret_value()
    msp_client_secret = config.MSP_CLIENT_SECRET.get_secret_value()
    msp_workspace_id = config.MSP_WORKSPACE_ID.get_secret_value()

    if not all([msp_client_id, msp_client_secret, msp_workspace_id]):
        raise ArubaClientError(
            "Missing MSP settings: ARUBA_MSP_CLIENT_ID, ARUBA_MSP_CLIENT_SECRET, ARUBA_MSP_WORKSPACE_ID"
        )

    msp_token = _get_msp_token(msp_client_id, msp_client_secret, msp_workspace_id, config.GREENLAKE_OAUTH_URL)
    return sorted(_fetch_msp_tenants(msp_token).keys())


def _paginate(
    fetch: Callable[[int], dict],
    *,
    page_size: int,
    only_first_page: bool = False,
    advance: Callable[[dict, list[dict]], int] = lambda page, items: len(items),
) -> Iterator[dict]:
    """Yield rows from an offset-paginated endpoint, page by page.

    ``fetch(offset)`` returns one raw page dict (and is where the caller does its
    own request, error handling and per-page logging). Iteration stops after a
    page that is empty, shorter than ``page_size``, advances by zero, or reaches
    the server-reported ``total`` — or immediately when ``only_first_page`` is set.
    The per-page ``advance`` defaults to the number of items returned.
    """
    offset = 0
    total: int | None = None
    while True:
        page = fetch(offset)
        if total is None:
            total = page.get("total")
        items = page.get("items", [])
        yield from items

        if only_first_page or not items or len(items) < page_size:
            return
        step = advance(page, items)
        if step == 0:
            return
        offset += step
        if isinstance(total, int) and offset >= total:
            return


def get_new_central_sites(
    conn: NewCentralBase, page_size: int = SITE_LIMIT, only_first_page: bool = False
) -> CentralResponse[list[dict], SiteRegistry]:
    """Sites with per-device-type health (``sites-device-health``) — see ``SiteRegistry``."""

    def fetch(offset: int) -> dict:
        page = MonitoringSites.list_sites_device_health(conn, limit=page_size, offset=offset)
        items = page.get("items", [])
        logger.info(f"Fetched {len(items)} sites, offset: {offset}, total: {page.get('total')}, page_size: {page_size}")
        return page

    sites = list(_paginate(fetch, page_size=page_size, only_first_page=only_first_page))
    return CentralResponse(sites, SiteRegistry.from_raw)


def get_new_central_site_configs(
    conn: NewCentralBase, page_size: int = 100, only_first_page: bool = False
) -> CentralResponse[list[dict], list[SiteConfig]]:
    """Site configuration (incl. address/city) from the new Central config API — see ``SiteConfig``.

    Offset-paginated against ``network-config/v1alpha1/sites`` via the raw
    ``conn.command`` interface (there is no pycentral monitoring class for it).
    Use ``.parsed()`` for ``list[SiteConfig]`` or ``.raw`` for the untouched
    rows (which ``SiteRegistry.enrich_addresses`` consumes directly).
    """

    def fetch(offset: int) -> dict:
        api_path = f"network-config/v1alpha1/sites?limit={page_size}&offset={offset}"
        response = conn.command(api_method="GET", api_path=api_path, app_name="new_central")
        if response.get("code") != 200:
            raise ArubaClientError(f"new_central site config API error {response.get('code')}: {response.get('msg')}")
        data: dict = response.get("msg", {})
        logger.debug(f"Fetched {len(data.get('items', []))} site configs, offset: {offset}, total: {data.get('total')}")
        return data

    # This endpoint advances by its own ``count`` (falling back to the page length).
    sites = list(
        _paginate(
            fetch,
            page_size=page_size,
            only_first_page=only_first_page,
            advance=lambda page, items: page.get("count", len(items)),
        )
    )
    return CentralResponse(sites, SiteConfig.list_from_raw)


def get_new_central_aps(
    conn: NewCentralBase,
    page_size: int = AP_LIMIT,
    only_first_page: bool = False,
    site: str | None = None,
) -> CentralResponse[list[dict], list[AccessPoint]]:
    """Access points (``network-monitoring/v1/aps``), optionally scoped to a ``site`` — see ``AccessPoint``."""
    logger.info("Getting APs from new_central", page_size=page_size, only_first_page=only_first_page, site=site)

    filter_str = f"siteId eq {site}" if site else None
    if only_first_page:
        rows = MonitoringAPs.get_aps(conn, filter_str=filter_str, limit=page_size).get("items", [])
    else:
        rows = MonitoringAPs.get_all_aps(conn, filter_str=filter_str)
    return CentralResponse(rows, AccessPoint.list_from_raw)
