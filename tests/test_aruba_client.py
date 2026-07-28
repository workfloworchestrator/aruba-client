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

import re
import time
from unittest.mock import Mock

import httpx
import pytest

from aruba_client.client import (
    ArubaClientError,
    ArubaCustomerNotFoundError,
    _exchange_for_tenant_token,
    _fetch_msp_tenants,
    _get_msp_token,
    _msp_token_cache,
    _paginate,
    _resolve_workspace_id,
    get_central_client,
    get_msp_tenant_names,
    get_new_central_aps,
    get_new_central_site_configs,
    get_new_central_sites,
)
from aruba_client.schema import AccessPoint, SiteConfig, SiteRegistry

FAKE_OAUTH_URL = "https://global.api.greenlake.hpe.com/authorization/v2/oauth2"


@pytest.fixture(autouse=True)
def _clear_caches():
    """Reset module-level caches between tests."""
    import aruba_client.client as mod

    mod._msp_token_cache.clear()
    mod._workspace_cache = {}
    mod._workspace_cache_expiry = 0.0
    yield
    mod._msp_token_cache.clear()
    mod._workspace_cache = {}
    mod._workspace_cache_expiry = 0.0


@pytest.fixture()
def msp_env(monkeypatch):
    monkeypatch.setenv("ARUBA_MSP_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("ARUBA_MSP_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("ARUBA_MSP_WORKSPACE_ID", "abc123")
    monkeypatch.setenv("ARUBA_BASE_URL", "https://de3.api.central.arubanetworks.com")
    monkeypatch.setenv("ARUBA_GREENLAKE_OAUTH_URL", FAKE_OAUTH_URL)


FAKE_MSP_TOKEN = "msp-tok"  # noqa: S105
FAKE_TENANT_TOKEN = "tenant-tok"  # noqa: S105
FAKE_CACHED_TOKEN = "cached-tok"  # noqa: S105

MSP_TOKEN_RESPONSE = {"access_token": FAKE_MSP_TOKEN, "expires_in": 7200}

TENANTS_RESPONSE = {
    "offset": 0,
    "count": 2,
    "total": 2,
    "items": [
        {"id": "aaaa-bbbb-cccc", "workspaceName": "ExampleUni", "type": "workspace"},
        {"id": "1111-2222-3333", "workspaceName": "DemoCollege", "type": "workspace"},
    ],
}

TENANT_TOKEN_RESPONSE = {"access_token": FAKE_TENANT_TOKEN, "expires_in": 900}


class TestGetCentralClient:
    def test_unknown_customer_raises(self, msp_env, httpx_mock):
        # No allow-list any more: an unknown customer fails at MSP workspace resolution instead.
        httpx_mock.add_response(url=re.compile(r".*/oauth2/abc123/token"), json=MSP_TOKEN_RESPONSE)
        httpx_mock.add_response(url=re.compile(r".*/msp-tenants"), json=TENANTS_RESPONSE)

        with pytest.raises(ArubaCustomerNotFoundError, match="not found among MSP-managed tenants"):
            get_central_client("NonExistent")

    def test_missing_msp_settings_raises(self, monkeypatch):
        monkeypatch.setenv("ARUBA_MSP_CLIENT_ID", "")
        monkeypatch.setenv("ARUBA_MSP_CLIENT_SECRET", "")
        monkeypatch.setenv("ARUBA_MSP_WORKSPACE_ID", "")
        monkeypatch.setenv("ARUBA_BASE_URL", "https://de3.api.central.arubanetworks.com")
        monkeypatch.setenv("ARUBA_GREENLAKE_OAUTH_URL", FAKE_OAUTH_URL)

        with pytest.raises(ArubaClientError, match="Missing MSP settings"):
            get_central_client("ExampleUni")

    def test_success_returns_newcentralbase(self, msp_env, httpx_mock):
        httpx_mock.add_response(url=re.compile(r".*/oauth2/abc123/token"), json=MSP_TOKEN_RESPONSE)
        httpx_mock.add_response(url=re.compile(r".*/msp-tenants"), json=TENANTS_RESPONSE)
        httpx_mock.add_response(url=re.compile(r".*/oauth2/aaaabbbbcccc/token"), json=TENANT_TOKEN_RESPONSE)

        client = get_central_client("ExampleUni")
        assert client is not None


class TestRequestRetry:
    """The GreenLake token/tenant calls retry transient failures (429/5xx + transport errors)."""

    @pytest.fixture(autouse=True)
    def _no_sleep(self, monkeypatch):
        # Don't actually wait for the exponential backoff during tests.
        monkeypatch.setattr("aruba_client.client.time.sleep", lambda *_: None)

    def test_retries_on_retryable_status_then_succeeds(self, httpx_mock):
        httpx_mock.add_response(status_code=503, text="busy")
        httpx_mock.add_response(json=MSP_TOKEN_RESPONSE)

        assert _get_msp_token("cid", "sec", "wid", FAKE_OAUTH_URL) == FAKE_MSP_TOKEN
        assert len(httpx_mock.get_requests()) == 2

    def test_retries_on_transport_error_then_succeeds(self, httpx_mock):
        httpx_mock.add_exception(httpx.ConnectError("boom"))
        httpx_mock.add_response(json=MSP_TOKEN_RESPONSE)

        assert _get_msp_token("cid", "sec", "wid", FAKE_OAUTH_URL) == FAKE_MSP_TOKEN
        assert len(httpx_mock.get_requests()) == 2

    def test_gives_up_after_max_attempts(self, httpx_mock):
        for _ in range(3):
            httpx_mock.add_exception(httpx.ConnectError("boom"))

        with pytest.raises(ArubaClientError, match="failed after 3 attempts"):
            _get_msp_token("cid", "sec", "wid", FAKE_OAUTH_URL)
        assert len(httpx_mock.get_requests()) == 3

    def test_non_retryable_status_is_not_retried(self, httpx_mock):
        httpx_mock.add_response(status_code=401, text="unauthorized")

        with pytest.raises(ArubaClientError, match="MSP token request failed"):
            _get_msp_token("cid", "sec", "wid", FAKE_OAUTH_URL)
        assert len(httpx_mock.get_requests()) == 1


class TestGetMspToken:
    def test_fetches_and_caches(self, httpx_mock):
        httpx_mock.add_response(json=MSP_TOKEN_RESPONSE)

        token = _get_msp_token("cid", "sec", "wid", FAKE_OAUTH_URL)
        assert token == FAKE_MSP_TOKEN
        assert ("cid:wid") in _msp_token_cache

    def test_returns_cached_token(self, httpx_mock):
        _msp_token_cache["cid:wid"] = (FAKE_CACHED_TOKEN, time.time() + 600)

        token = _get_msp_token("cid", "sec", "wid", FAKE_OAUTH_URL)
        assert token == FAKE_CACHED_TOKEN
        assert len(httpx_mock.get_requests()) == 0

    def test_error_raises(self, httpx_mock):
        httpx_mock.add_response(status_code=401, text="unauthorized")

        with pytest.raises(ArubaClientError, match="MSP token request failed"):
            _get_msp_token("cid", "sec", "wid", FAKE_OAUTH_URL)


class TestFetchMspTenants:
    def test_parses_response(self, httpx_mock):
        httpx_mock.add_response(json=TENANTS_RESPONSE)

        result = _fetch_msp_tenants("tok")
        assert result == {"EXAMPLEUNI": "aaaabbbbcccc", "DEMOCOLLEGE": "111122223333"}

    def test_strips_hyphens_from_ids(self, httpx_mock):
        httpx_mock.add_response(json={"items": [{"id": "aa-bb-cc", "workspaceName": "Test"}]})
        result = _fetch_msp_tenants("tok")
        assert result["TEST"] == "aabbcc"

    def test_error_raises(self, httpx_mock):
        # 403 is not a retryable status, so a single response exercises the error path.
        httpx_mock.add_response(status_code=403, text="forbidden")

        with pytest.raises(ArubaClientError, match="Failed to fetch MSP tenants"):
            _fetch_msp_tenants("tok")


class TestGetMspTenantNames:
    def test_returns_sorted_upper_cased_names(self, msp_env, httpx_mock):
        httpx_mock.add_response(url=re.compile(r".*/oauth2/abc123/token"), json=MSP_TOKEN_RESPONSE)
        httpx_mock.add_response(url=re.compile(r".*/msp-tenants"), json=TENANTS_RESPONSE)

        assert get_msp_tenant_names() == ["DEMOCOLLEGE", "EXAMPLEUNI"]

    def test_missing_msp_settings_raises(self, monkeypatch):
        monkeypatch.setenv("ARUBA_MSP_CLIENT_ID", "")
        monkeypatch.setenv("ARUBA_MSP_CLIENT_SECRET", "")
        monkeypatch.setenv("ARUBA_MSP_WORKSPACE_ID", "")
        monkeypatch.setenv("ARUBA_BASE_URL", "https://de3.api.central.arubanetworks.com")
        monkeypatch.setenv("ARUBA_GREENLAKE_OAUTH_URL", FAKE_OAUTH_URL)

        with pytest.raises(ArubaClientError, match="Missing MSP settings"):
            get_msp_tenant_names()


class TestResolveWorkspaceId:
    def test_cache_miss_fetches(self, httpx_mock):
        httpx_mock.add_response(json=TENANTS_RESPONSE)

        wid = _resolve_workspace_id("tok", "EXAMPLEUNI")
        assert wid == "aaaabbbbcccc"

    def test_cache_hit(self, httpx_mock):
        import aruba_client.client as mod

        mod._workspace_cache["EXAMPLEUNI"] = "cached-wid"
        mod._workspace_cache_expiry = time.time() + 600

        wid = _resolve_workspace_id("tok", "EXAMPLEUNI")
        assert wid == "cached-wid"
        assert len(httpx_mock.get_requests()) == 0

    def test_case_insensitive(self, httpx_mock):
        httpx_mock.add_response(json=TENANTS_RESPONSE)

        wid = _resolve_workspace_id("tok", "exampleuni")
        assert wid == "aaaabbbbcccc"

    def test_not_found_raises(self, httpx_mock):
        httpx_mock.add_response(json=TENANTS_RESPONSE)

        with pytest.raises(ArubaCustomerNotFoundError, match="not found among MSP-managed tenants"):
            _resolve_workspace_id("tok", "NonExistent")


class TestExchangeForTenantToken:
    def test_success(self, httpx_mock):
        httpx_mock.add_response(json=TENANT_TOKEN_RESPONSE)

        token = _exchange_for_tenant_token("msp-tok", "tenant-wid", FAKE_OAUTH_URL)
        assert token == FAKE_TENANT_TOKEN

    def test_error_raises(self, httpx_mock):
        httpx_mock.add_response(status_code=400, text="bad request")

        with pytest.raises(ArubaClientError, match="Tenant token exchange failed"):
            _exchange_for_tenant_token("msp-tok", "tenant-wid", FAKE_OAUTH_URL)


class TestPaginate:
    """``_paginate`` takes an injected ``fetch`` callable, so the stop-logic is
    testable in isolation without monkeypatching any module-level SDK call.
    """

    @staticmethod
    def _fetch_from(pages):
        """Build a ``fetch(offset)`` that returns successive ``pages`` and records the offsets it saw."""
        calls = []

        def fetch(offset):
            calls.append(offset)
            return pages[len(calls) - 1]

        return fetch, calls

    def test_stops_on_partial_page(self):
        fetch, calls = self._fetch_from(
            [
                {"items": [{"id": "a"}, {"id": "b"}], "total": 5},
                {"items": [{"id": "c"}], "total": 5},  # short page -> last page
            ]
        )
        rows = list(_paginate(fetch, page_size=2))
        assert [r["id"] for r in rows] == ["a", "b", "c"]
        assert calls == [0, 2]  # offset advanced by the first page's length

    def test_stops_when_offset_reaches_total(self):
        fetch, calls = self._fetch_from(
            [
                {"items": [{"id": "a"}, {"id": "b"}], "total": 2},  # full page, but total already reached
            ]
        )
        rows = list(_paginate(fetch, page_size=2))
        assert [r["id"] for r in rows] == ["a", "b"]
        assert calls == [0]

    def test_only_first_page(self):
        fetch, calls = self._fetch_from([{"items": [{"id": "a"}] * 3, "total": 99}])
        rows = list(_paginate(fetch, page_size=3, only_first_page=True))
        assert len(rows) == 3
        assert calls == [0]

    def test_custom_advance(self):
        # The config endpoint advances by its own ``count`` rather than len(items).
        fetch, calls = self._fetch_from(
            [
                {"items": [{"id": "a"}, {"id": "b"}], "count": 2, "total": 3},
                {"items": [{"id": "c"}], "count": 1, "total": 3},
            ]
        )
        rows = list(_paginate(fetch, page_size=2, advance=lambda page, items: page.get("count", len(items))))
        assert [r["id"] for r in rows] == ["a", "b", "c"]
        assert calls == [0, 2]


class TestGetNewCentralSites:
    """``get_new_central_sites`` delegates to ``MonitoringSites.list_sites_device_health``."""

    def test_single_page(self, monkeypatch):
        mock = Mock(return_value={"items": [{"id": "s1", "siteName": "Site 1"}], "total": 1})
        monkeypatch.setattr("aruba_client.client.MonitoringSites.list_sites_device_health", mock)

        conn = Mock()
        result = get_new_central_sites(conn, page_size=100)

        assert result.raw == [{"id": "s1", "siteName": "Site 1"}]
        mock.assert_called_once_with(conn, limit=100, offset=0)

    def test_paginates_until_total_reached(self, monkeypatch):
        pages = [
            {"items": [{"id": "s1"}, {"id": "s2"}], "total": 3},
            {"items": [{"id": "s3"}], "total": 3},
        ]
        mock = Mock(side_effect=pages)
        monkeypatch.setattr("aruba_client.client.MonitoringSites.list_sites_device_health", mock)

        result = get_new_central_sites(Mock(), page_size=2)

        assert [s["id"] for s in result.raw] == ["s1", "s2", "s3"]
        assert mock.call_count == 2

    def test_only_first_page_stops_after_one_call(self, monkeypatch):
        mock = Mock(return_value={"items": [{"id": "s1"}] * 5, "total": 50})
        monkeypatch.setattr("aruba_client.client.MonitoringSites.list_sites_device_health", mock)

        result = get_new_central_sites(Mock(), page_size=5, only_first_page=True)

        assert len(result.raw) == 5
        assert mock.call_count == 1

    def test_parsed_returns_site_registry(self, monkeypatch):
        mock = Mock(return_value={"items": [{"id": "s1", "siteName": "Site 1"}], "total": 1})
        monkeypatch.setattr("aruba_client.client.MonitoringSites.list_sites_device_health", mock)

        registry = get_new_central_sites(Mock()).parsed()

        assert isinstance(registry, SiteRegistry)
        assert registry.resolve_name("s1") == "Site 1"


class TestGetNewCentralAps:
    """``get_new_central_aps`` delegates to ``MonitoringAPs`` (cursor pagination + site filter)."""

    def test_fetches_all_pages_via_sdk(self, monkeypatch):
        mock = Mock(return_value=[{"serialNumber": "SN1"}, {"serialNumber": "SN2"}])
        monkeypatch.setattr("aruba_client.client.MonitoringAPs.get_all_aps", mock)

        result = get_new_central_aps(Mock())

        assert result.raw == [{"serialNumber": "SN1"}, {"serialNumber": "SN2"}]
        _, kwargs = mock.call_args
        assert kwargs["filter_str"] is None

    def test_site_is_translated_to_filter(self, monkeypatch):
        mock = Mock(return_value=[])
        monkeypatch.setattr("aruba_client.client.MonitoringAPs.get_all_aps", mock)

        get_new_central_aps(Mock(), site="site-001")

        _, kwargs = mock.call_args
        assert kwargs["filter_str"] == "siteId eq site-001"

    def test_only_first_page_uses_single_page_endpoint(self, monkeypatch):
        page_mock = Mock(return_value={"items": [{"serialNumber": "SN1"}], "total": 9})
        all_mock = Mock()
        monkeypatch.setattr("aruba_client.client.MonitoringAPs.get_aps", page_mock)
        monkeypatch.setattr("aruba_client.client.MonitoringAPs.get_all_aps", all_mock)

        result = get_new_central_aps(Mock(), page_size=50, only_first_page=True, site="site-001")

        assert result.raw == [{"serialNumber": "SN1"}]
        all_mock.assert_not_called()
        _, kwargs = page_mock.call_args
        assert kwargs["filter_str"] == "siteId eq site-001"
        assert kwargs["limit"] == 50

    def test_parsed_returns_access_points(self, monkeypatch):
        mock = Mock(return_value=[{"serialNumber": "SN1", "deviceName": "ap1", "siteId": "s1"}])
        monkeypatch.setattr("aruba_client.client.MonitoringAPs.get_all_aps", mock)

        aps = get_new_central_aps(Mock()).parsed()

        assert [isinstance(ap, AccessPoint) for ap in aps] == [True]
        assert aps[0].serial == "SN1"


class TestGetNewCentralSiteConfigs:
    """``get_new_central_site_configs`` offset-paginates the raw ``network-config`` API via ``conn.command``."""

    def test_single_page_returns_central_response(self):
        conn = Mock()
        conn.command.return_value = {
            "code": 200,
            "msg": {"items": [{"id": "s1", "address": "Voorbeeldstraat 1", "city": "Amsterdam"}]},
        }

        result = get_new_central_site_configs(conn, page_size=100)

        # .raw is the untouched payload (what enrich_addresses consumes)...
        assert result.raw == [{"id": "s1", "address": "Voorbeeldstraat 1", "city": "Amsterdam"}]
        # ...and .parsed() yields typed SiteConfig rows.
        parsed = result.parsed()
        assert isinstance(parsed[0], SiteConfig)
        assert parsed[0].id == "s1"
        assert parsed[0].address == "Voorbeeldstraat 1"
        assert parsed[0].city == "Amsterdam"
        _, kwargs = conn.command.call_args
        assert kwargs["api_path"] == "network-config/v1alpha1/sites?limit=100&offset=0"
