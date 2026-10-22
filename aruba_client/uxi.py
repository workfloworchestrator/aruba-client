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

"""Read-only wrappers around the HPE Aruba User Experience Insight (UXI) API.

UXI sensors are not part of Aruba Central. Their API lives on its own HPE GreenLake
service (``https://api.capenetworks.com/networking-uxi/v1alpha1``, an alpha API with
one host for every region; the region is selected with the ``x-region`` header) and
is authorised by a GreenLake *API client* bound to the "User Experience Insight"
service. Such a client is pinned to the UXI instance (dashboard) of the workspace it was
created in (the token's ``application_instance_id`` claim); the Aruba Central MSP token is
rejected with 403 and the RFC 8693 tenant exchange keeps pointing at the MSP workspace's own
dashboard. UXI therefore has its own credentials, one set per dashboard:
:class:`~aruba_client.config.UxiConfig` (``ARUBA_UXI_*`` environment variables).

List endpoints are cursor-paginated (``limit`` at most 100, ``next`` cursor) and the
API allows 5 requests per second per customer; 429s and transport errors are retried
with backoff by :func:`aruba_client._http._request_with_retry`.

Each getter returns a :class:`~aruba_client.schema.CentralResponse`: call ``.parsed()``
for the typed model or ``.raw`` for the untouched payload. Response shapes are
documented by the ``Uxi*`` models in :mod:`aruba_client.schema`. Get a ``client``
from :func:`get_uxi_client`, or wrap a bearer token you already hold in
:class:`UxiClient`.
"""

import time
from collections.abc import Collection, Iterator, Mapping
from http import HTTPStatus
from typing import get_args

import httpx
import structlog

from aruba_client._http import (
    _DEFAULT_TOKEN_TTL,
    _TOKEN_EXPIRY_BUFFER,
    ArubaClientError,
    _request_with_retry,
)
from aruba_client.config import UxiConfig, UxiRegion
from aruba_client.schema import (
    CentralResponse,
    UxiGroup,
    UxiGroupRegistry,
    UxiSensor,
    UxiSensorGroupAssignment,
    UxiSensorStatus,
)

logger = structlog.get_logger(__name__)

UXI_BASE_URL = "https://api.capenetworks.com/networking-uxi/v1alpha1"
UXI_OAUTH_TOKEN_URL = "https://sso.common.cloud.hpe.com/as/token.oauth2"
UXI_REGIONS: tuple[str, ...] = get_args(UxiRegion)
UXI_PAGE_SIZE_MAX = 100

# The default httpx timeout (5 s) is tight for a 100-item page; connect fast, read patiently.
_UXI_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
# Guard against an API that keeps handing out cursors: 1000 pages of 100 is far beyond any dashboard.
_MAX_PAGES = 1000

_uxi_token_cache: dict[str, tuple[str, float]] = {}  # client_id -> (access_token, expiry epoch)


class UxiGroupNotFoundError(ArubaClientError):
    """No UXI group carries the requested name."""


def _get_uxi_token(client_id: str, client_secret: str, token_url: str) -> str:
    """Obtain a UXI access token via client_credentials grant.

    Tokens are valid for about two hours and are cached until five minutes before expiry.
    """
    cached = _uxi_token_cache.get(client_id)
    if cached and cached[1] > time.time():
        logger.info("Using cached UXI token")
        return cached[0]

    logger.info("Fetching UXI token", token_url=token_url)
    response = _request_with_retry(
        "POST",
        token_url,
        context="UXI token request",
        data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if response.status_code != HTTPStatus.OK:
        raise ArubaClientError(f"UXI token request failed ({response.status_code}): {response.text}")

    token_data = response.json()
    access_token = token_data["access_token"]
    expires_in = token_data.get("expires_in", _DEFAULT_TOKEN_TTL)
    _uxi_token_cache[client_id] = (access_token, time.time() + expires_in - _TOKEN_EXPIRY_BUFFER)

    logger.info("UXI token obtained", expires_in=expires_in)
    return access_token


def _error_message(path: str, response: httpx.Response) -> str:
    """Describe a failed UXI response on one line, status code first, so callers can show it verbatim."""
    status = response.status_code
    try:
        body = response.json()
    except ValueError:
        body = None

    if isinstance(body, dict):
        if "errorCode" in body:
            # The documented GreenLake error envelope: debugId, errorCode, httpStatusCode, message.
            debug = f" [debugId={body['debugId']}]" if body.get("debugId") else ""
            return f"UXI GET {path} failed ({status} {body['errorCode']}): {body.get('message', '')}{debug}"
        if isinstance(body.get("detail"), list):
            # The OpenAPI spec also documents FastAPI-style validation errors (422 with ``detail``);
            # live, an out-of-range ``limit`` is a 400 in the GreenLake envelope above.
            problems = "; ".join(
                f"{'.'.join(str(part) for part in item.get('loc', []))}: {item.get('msg', '')}"
                for item in body["detail"]
            )
            return f"UXI GET {path} failed ({status}): {problems}"

    text = " ".join(response.text.split())[:200]
    return f"UXI GET {path} failed ({status}): {text}"


class UxiClient:
    """Bearer-token client for one UXI region.

    Build it with :func:`get_uxi_client` (client_credentials against ``ARUBA_UXI_*``),
    or pass any bearer token you already hold. The token is never logged or shown in
    ``repr``. ``base_url`` is the versioned API root; ``path`` arguments are appended to it.
    """

    def __init__(self, token: str, *, region: UxiRegion, base_url: str = UXI_BASE_URL) -> None:
        if region not in UXI_REGIONS:
            raise ValueError(f"Unknown UXI region {region!r}; expected one of {UXI_REGIONS}")
        self._token = token
        self.region = region
        self.base_url = base_url.rstrip("/")

    def __repr__(self) -> str:
        return f"UxiClient(region={self.region!r}, base_url={self.base_url!r})"

    def get(self, path: str, *, params: Mapping[str, str | int | None] | None = None) -> dict:
        """GET one JSON document from ``path`` (e.g. ``/groups``); ``None`` params are dropped.

        Raises :class:`ArubaClientError` (one line, status code first) on any non-200 response.
        """
        query = {key: value for key, value in (params or {}).items() if value is not None}
        response = _request_with_retry(
            "GET",
            f"{self.base_url}{path}",
            context=f"UXI GET {path}",
            headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json", "x-region": self.region},
            params=query,
            timeout=_UXI_TIMEOUT,
        )
        if response.status_code != HTTPStatus.OK:
            raise ArubaClientError(_error_message(path, response))
        try:
            return response.json()
        except ValueError as exc:
            raise ArubaClientError(f"UXI GET {path} returned non-JSON ({response.status_code})") from exc

    def iter_items(
        self,
        path: str,
        *,
        params: Mapping[str, str | int | None] | None = None,
        page_size: int = UXI_PAGE_SIZE_MAX,
        only_first_page: bool = False,
    ) -> Iterator[dict]:
        """Yield the ``items`` of a cursor-paginated list endpoint, page by page.

        Follows the ``next`` cursor until the API returns none (``null``, missing or
        empty), a page comes back without items, or ``only_first_page`` is set. A cursor
        handed out twice, or more than ``_MAX_PAGES`` pages, stops the loop with a
        warning instead of spinning on a misbehaving API.
        """
        if not 1 <= page_size <= UXI_PAGE_SIZE_MAX:
            raise ValueError(f"page_size must be between 1 and {UXI_PAGE_SIZE_MAX}, got {page_size}")

        cursor: str | None = None
        seen: set[str] = set()
        for page_no in range(1, _MAX_PAGES + 1):
            page = self.get(path, params={**(params or {}), "limit": page_size, "next": cursor})
            items = page.get("items") or []
            cursor = page.get("next") or None
            logger.debug("Fetched UXI page", path=path, page=page_no, count=len(items), has_next=cursor is not None)
            yield from items

            if only_first_page or cursor is None or not items:
                return
            if cursor in seen:
                logger.warning("UXI pagination handed out a cursor twice; stopping", path=path, page=page_no)
                return
            seen.add(cursor)
        logger.warning("UXI pagination stopped at the page limit", path=path, pages=_MAX_PAGES)


def get_uxi_client(*, config: UxiConfig | None = None) -> UxiClient:
    """Create a :class:`UxiClient` from UXI API-client credentials (client_credentials grant).

    If ``config`` is not provided, configuration is read from ``ARUBA_UXI_*`` environment variables.
    """
    if config is None:
        config = UxiConfig()

    client_id = config.CLIENT_ID.get_secret_value()
    client_secret = config.CLIENT_SECRET.get_secret_value()
    if not all([client_id, client_secret]):
        raise ArubaClientError("Missing UXI settings: ARUBA_UXI_CLIENT_ID, ARUBA_UXI_CLIENT_SECRET")

    token = _get_uxi_token(client_id, client_secret, config.OAUTH_TOKEN_URL)
    return UxiClient(token, region=config.REGION, base_url=config.BASE_URL)


def get_groups(
    client: UxiClient, *, page_size: int = UXI_PAGE_SIZE_MAX, only_first_page: bool = False
) -> CentralResponse[list[dict], UxiGroupRegistry]:
    """The group tree (``/groups``) as a ``UxiGroupRegistry`` — see ``UxiGroup``."""
    rows = list(client.iter_items("/groups", page_size=page_size, only_first_page=only_first_page))
    return CentralResponse(rows, UxiGroupRegistry.from_raw)


def get_sensors(
    client: UxiClient,
    *,
    sensor_id: str | None = None,
    page_size: int = UXI_PAGE_SIZE_MAX,
    only_first_page: bool = False,
) -> CentralResponse[list[dict], list[UxiSensor]]:
    """Sensors (``/sensors``), optionally just the one with ``sensor_id`` — see ``UxiSensor``.

    There is no ``GET /sensors/{id}``; a single sensor is read through the ``id`` filter.
    """
    rows = list(
        client.iter_items("/sensors", params={"id": sensor_id}, page_size=page_size, only_first_page=only_first_page)
    )
    return CentralResponse(rows, UxiSensor.list_from_raw)


def get_sensor_group_assignments(
    client: UxiClient, *, page_size: int = UXI_PAGE_SIZE_MAX, only_first_page: bool = False
) -> CentralResponse[list[dict], list[UxiSensorGroupAssignment]]:
    """Which sensor sits in which group (``/sensor-group-assignments``) — see ``UxiSensorGroupAssignment``."""
    rows = list(client.iter_items("/sensor-group-assignments", page_size=page_size, only_first_page=only_first_page))
    return CentralResponse(rows, UxiSensorGroupAssignment.list_from_raw)


def get_sensor_status(client: UxiClient, sensor_id: str) -> CentralResponse[dict, UxiSensorStatus]:
    """Live status of one sensor (``/sensors/{id}/status``) — see ``UxiSensorStatus``."""
    return CentralResponse(client.get(f"/sensors/{sensor_id}/status"), UxiSensorStatus.from_raw)


def find_group(registry: UxiGroupRegistry, name: str) -> UxiGroup:
    """The group called exactly ``name`` (case-sensitive), e.g. the UXI group named after a Central site.

    A UXI group name is unique only among siblings, so it may occur more than once in the
    tree; that raises :class:`ArubaClientError` listing the candidate paths rather than
    silently picking one. Raises :class:`UxiGroupNotFoundError` when no group matches.
    """
    matches = [group for group in registry.groups if group.name == name]
    if not matches:
        raise UxiGroupNotFoundError(
            f"UXI group '{name}' not found. Known groups: {sorted(group.name for group in registry.groups)}"
        )
    if len(matches) > 1:
        raise ArubaClientError(f"UXI group name '{name}' is ambiguous: {[group.path for group in matches]}")
    return matches[0]


def get_group_sensors(client: UxiClient, group_ids: Collection[str]) -> CentralResponse[list[dict], list[UxiSensor]]:
    """Sensors assigned to any of ``group_ids`` — see ``UxiSensor``.

    Pass ``{group.id}`` for the group alone or ``registry.subtree_ids(group)`` to include its
    descendants. ``/sensor-group-assignments`` is the authoritative sensor-to-group mapping
    (``UxiSensor.group_path`` is a nullable, denormalised copy), so this reads the
    assignments and then the sensor list once and filters it; it never issues one request
    per sensor against the 5 req/s rate limit.
    """
    wanted_groups = set(group_ids)
    assignments = get_sensor_group_assignments(client).parsed()
    wanted = {a.sensor_id for a in assignments if a.group_id in wanted_groups}
    if not wanted:
        logger.info("No UXI sensors assigned", groups=sorted(wanted_groups))
        return CentralResponse([], UxiSensor.list_from_raw)

    rows = [row for row in get_sensors(client).raw if row.get("id") in wanted]
    if missing := wanted - {row.get("id") for row in rows}:
        logger.warning("UXI assignments reference sensors missing from the sensor list", sensor_ids=sorted(missing))
    logger.info("UXI group sensors", groups=len(wanted_groups), assigned=len(wanted), found=len(rows))
    return CentralResponse(rows, UxiSensor.list_from_raw)
