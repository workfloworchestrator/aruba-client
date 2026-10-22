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

"""Tests for the UXI module: token, client, pagination, getters and the group helpers.

Every HTTP call is served by pytest-httpx; all names, ids and serials are made up.
"""

import re
import time

import httpx
import pytest
from pydantic import ValidationError

import aruba_client.uxi as uxi_module
from aruba_client import UxiClient, UxiConfig, UxiGroupNotFoundError, get_uxi_client, uxi
from aruba_client.client import ArubaClientError
from aruba_client.schema import UxiGroupRegistry, UxiSensor, UxiSensorGroupAssignment, UxiSensorStatus

UXI_BASE = "https://api.capenetworks.com/networking-uxi/v1alpha1"
TOKEN_URL = "https://sso.common.cloud.hpe.com/as/token.oauth2"

FAKE_UXI_TOKEN = "uxi-tok"  # noqa: S105
FAKE_CACHED_TOKEN = "cached-uxi-tok"  # noqa: S105
TOKEN_RESPONSE = {"access_token": FAKE_UXI_TOKEN, "token_type": "Bearer", "expires_in": 7199}

# A small group tree: Example Org > Example Campus > Building A, plus a second "Building A"
# under Demo Campus (group names are unique among siblings only).
ORG_ID = "00000000-0000-4000-8000-000000000001"
CAMPUS_ID = "00000000-0000-4000-8000-000000000002"
BUILDING_ID = "00000000-0000-4000-8000-000000000003"
DEMO_CAMPUS_ID = "00000000-0000-4000-8000-000000000004"
DEMO_BUILDING_ID = "00000000-0000-4000-8000-000000000005"

GROUPS = [
    {"id": ORG_ID, "name": "Example Org", "parent": None, "path": "g0000001", "type": "networking-uxi/group"},
    {"id": CAMPUS_ID, "name": "Example Campus", "parent": {"id": ORG_ID}, "path": "g0000001.g0000002"},
    {"id": BUILDING_ID, "name": "Building A", "parent": {"id": CAMPUS_ID}, "path": "g0000001.g0000002.g0000003"},
    {"id": DEMO_CAMPUS_ID, "name": "Demo Campus", "parent": {"id": ORG_ID}, "path": "g0000001.g0000004"},
    {
        "id": DEMO_BUILDING_ID,
        "name": "Building A",
        "parent": {"id": DEMO_CAMPUS_ID},
        "path": "g0000001.g0000004.g0000005",
    },
]

SENSOR_1 = "00000000-0000-4000-8000-000000000101"
SENSOR_2 = "00000000-0000-4000-8000-000000000102"
SENSOR_3 = "00000000-0000-4000-8000-000000000103"

SENSORS = [
    {
        "id": SENSOR_1,
        "serial": "SENSORSERIAL01",
        "name": "demo-sensor-01",
        "groupName": "Example Campus",
        "groupPath": "g0000001.g0000002",
        "modelNumber": "UX-G6EC",
        "wifiMacAddress": "00:11:22:33:44:51",
        "ethernetMacAddress": "00:11:22:33:44:52",
        "addressNote": None,
        "longitude": None,
        "latitude": None,
        "notes": None,
        "pcapMode": "light",
        "type": "networking-uxi/sensor",
    },
    {
        "id": SENSOR_2,
        "serial": "SENSORSERIAL02",
        "name": "demo-sensor-02",
        "groupName": "Building A",
        "groupPath": "g0000001.g0000002.g0000003",
        "modelNumber": "UX-G6EC",
        "wifiMacAddress": "00:11:22:33:44:53",
        "ethernetMacAddress": "00:11:22:33:44:54",
        "addressNote": "Lobby",
        "longitude": 4.9,
        "latitude": 52.3,
        "notes": "spare",
        "pcapMode": None,
        "type": "networking-uxi/sensor",
    },
    {
        "id": SENSOR_3,
        "serial": "SENSORSERIAL03",
        "name": "demo-sensor-03",
        "groupName": "Demo Campus",
        "groupPath": "g0000001.g0000004",
        "modelNumber": "UX-F5C",
        "wifiMacAddress": None,
        "ethernetMacAddress": None,
        "addressNote": None,
        "longitude": None,
        "latitude": None,
        "notes": None,
        "pcapMode": "off",
        "type": "networking-uxi/sensor",
    },
]

ASSIGNMENTS = [
    {
        "id": "a-1",
        "group": {"id": CAMPUS_ID},
        "sensor": {"id": SENSOR_1},
        "type": "networking-uxi/sensor-group-assignment",
    },
    {"id": "a-2", "group": {"id": BUILDING_ID}, "sensor": {"id": SENSOR_2}},
    {"id": "a-3", "group": {"id": DEMO_CAMPUS_ID}, "sensor": {"id": SENSOR_3}},
]

STATUS_OK = {"isOnline": True, "isTesting": True, "issues": []}
STATUS_WITH_ISSUE = {
    "isOnline": False,
    "isTesting": None,
    "issues": [
        {
            "code": "EXTERNAL_SSL_ERROR",
            "context": {
                "customerId": "00000000-0000-4000-8000-000000000900",
                "sensorId": SENSOR_2,
                "networkName": "demo-ssid",
                "serviceTestName": "Demo SSL Test",
            },
            "id": "00000000-0000-4000-8000-000000000800",
            "incidentId": None,
            "severity": "ERROR",
            "status": "CONFIRMED",
            "timestamp": "2026-06-12T18:00:00Z",
        }
    ],
}

ERROR_403 = {
    "debugId": "dbg-0001",
    "errorCode": "HPE_GL_ERROR_FORBIDDEN",
    "httpStatusCode": 403,
    "message": "The user has insufficient permissions to complete the request.",
}
ERROR_429 = {
    "debugId": "dbg-0002",
    "errorCode": "HPE_GL_ERROR_TOO_MANY_REQUESTS",
    "httpStatusCode": 429,
    "message": "Slow down",
}


def page(items: list[dict], next_cursor: str | None = None) -> dict:
    return {"count": len(items), "items": items, "next": next_cursor}


@pytest.fixture(autouse=True)
def _clear_token_cache():
    uxi_module._uxi_token_cache.clear()
    yield
    uxi_module._uxi_token_cache.clear()


@pytest.fixture()
def _no_sleep(monkeypatch):
    # Don't actually wait for the exponential backoff during tests.
    monkeypatch.setattr("aruba_client._http.time.sleep", lambda *_: None)


@pytest.fixture()
def uxi_env(monkeypatch):
    monkeypatch.setenv("ARUBA_UXI_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("ARUBA_UXI_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("ARUBA_UXI_REGION", "eu-production")


@pytest.fixture()
def client() -> UxiClient:
    return UxiClient(FAKE_UXI_TOKEN, region="eu-production")


class TestUxiConfig:
    def test_reads_env_with_prefix_and_defaults(self, uxi_env):
        config = UxiConfig()

        assert config.CLIENT_ID.get_secret_value() == "test-client-id"
        assert config.CLIENT_SECRET.get_secret_value() == "test-secret"
        assert config.REGION == "eu-production"
        assert config.OAUTH_TOKEN_URL == TOKEN_URL
        assert config.BASE_URL == UXI_BASE

    def test_region_is_required(self, uxi_env, monkeypatch):
        monkeypatch.delenv("ARUBA_UXI_REGION")

        with pytest.raises(ValidationError, match="REGION"):
            UxiConfig()

    def test_unknown_region_is_rejected(self, uxi_env, monkeypatch):
        monkeypatch.setenv("ARUBA_UXI_REGION", "eu")

        with pytest.raises(ValidationError, match="REGION"):
            UxiConfig()


class TestGetUxiToken:
    def test_posts_client_credentials_form_and_caches(self, httpx_mock):
        httpx_mock.add_response(
            url=TOKEN_URL,
            method="POST",
            match_content=b"grant_type=client_credentials&client_id=cid&client_secret=sec",
            json=TOKEN_RESPONSE,
        )

        before = time.time()
        token = uxi_module._get_uxi_token("cid", "sec", TOKEN_URL)

        assert token == FAKE_UXI_TOKEN
        cached_token, expiry = uxi_module._uxi_token_cache["cid"]
        assert cached_token == FAKE_UXI_TOKEN
        # Cached until five minutes before the 7199 s lifetime runs out.
        assert before + 7199 - 300 <= expiry <= time.time() + 7199 - 300

    def test_returns_cached_token(self, httpx_mock):
        uxi_module._uxi_token_cache["cid"] = (FAKE_CACHED_TOKEN, time.time() + 600)

        assert uxi_module._get_uxi_token("cid", "sec", TOKEN_URL) == FAKE_CACHED_TOKEN
        assert len(httpx_mock.get_requests()) == 0

    def test_expired_cache_entry_is_refreshed(self, httpx_mock):
        uxi_module._uxi_token_cache["cid"] = (FAKE_CACHED_TOKEN, time.time() - 1)
        httpx_mock.add_response(url=TOKEN_URL, json=TOKEN_RESPONSE)

        assert uxi_module._get_uxi_token("cid", "sec", TOKEN_URL) == FAKE_UXI_TOKEN

    def test_error_raises(self, httpx_mock):
        httpx_mock.add_response(url=TOKEN_URL, status_code=401, text="unauthorized")

        with pytest.raises(ArubaClientError, match=r"UXI token request failed \(401\)"):
            uxi_module._get_uxi_token("cid", "sec", TOKEN_URL)

    @pytest.mark.usefixtures("_no_sleep")
    def test_retries_transient_failure_then_succeeds(self, httpx_mock):
        httpx_mock.add_response(url=TOKEN_URL, status_code=503, text="busy")
        httpx_mock.add_response(url=TOKEN_URL, json=TOKEN_RESPONSE)

        assert uxi_module._get_uxi_token("cid", "sec", TOKEN_URL) == FAKE_UXI_TOKEN
        assert len(httpx_mock.get_requests()) == 2


class TestGetUxiClient:
    def test_builds_client_from_env(self, uxi_env, httpx_mock):
        httpx_mock.add_response(url=TOKEN_URL, json=TOKEN_RESPONSE)

        client = get_uxi_client()

        assert client.region == "eu-production"
        assert client.base_url == UXI_BASE

    def test_explicit_config(self, httpx_mock):
        httpx_mock.add_response(url="https://sso.example.org/token", json=TOKEN_RESPONSE)
        config = UxiConfig(
            CLIENT_ID="cid",
            CLIENT_SECRET="sec",
            REGION="us-production",
            OAUTH_TOKEN_URL="https://sso.example.org/token",
            BASE_URL="https://uxi.example.org/v1alpha1/",
        )

        client = get_uxi_client(config=config)

        assert client.region == "us-production"
        assert client.base_url == "https://uxi.example.org/v1alpha1"  # trailing slash stripped

    def test_missing_settings_raises(self, uxi_env, monkeypatch):
        monkeypatch.setenv("ARUBA_UXI_CLIENT_ID", "")
        monkeypatch.setenv("ARUBA_UXI_CLIENT_SECRET", "")

        with pytest.raises(ArubaClientError, match="Missing UXI settings"):
            get_uxi_client()


class TestUxiClientGet:
    def test_sends_bearer_region_and_accept_headers(self, client, httpx_mock):
        httpx_mock.add_response(
            url=f"{UXI_BASE}/groups?limit=1",
            match_headers={
                "Authorization": f"Bearer {FAKE_UXI_TOKEN}",
                "x-region": "eu-production",
                "Accept": "application/json",
            },
            json=page([]),
        )

        assert client.get("/groups", params={"limit": 1}) == page([])

    def test_none_params_are_dropped(self, client, httpx_mock):
        httpx_mock.add_response(url=f"{UXI_BASE}/sensors?limit=5", json=page([]))

        client.get("/sensors", params={"id": None, "limit": 5})

        assert "id=" not in str(httpx_mock.get_request().url)

    def test_maps_greenlake_error_envelope(self, client, httpx_mock):
        httpx_mock.add_response(url=f"{UXI_BASE}/groups", status_code=403, json=ERROR_403)

        with pytest.raises(ArubaClientError) as excinfo:
            client.get("/groups")

        message = str(excinfo.value)
        assert message.startswith("UXI GET /groups failed (403 HPE_GL_ERROR_FORBIDDEN): The user has insufficient")
        assert message.endswith("[debugId=dbg-0001]")
        assert "\n" not in message

    def test_maps_request_validation_error(self, client, httpx_mock):
        # The FastAPI-style shape the OpenAPI spec documents for 422; live, an out-of-range ``limit`` answers
        # 400 HPE_GL_ERROR_BAD_REQUEST in the GreenLake envelope, which the errorCode branch covers.
        detail = {
            "detail": [{"loc": ["query", "limit"], "msg": "Input should be less than or equal to 100", "type": "x"}]
        }
        httpx_mock.add_response(url=f"{UXI_BASE}/groups", status_code=422, json=detail)

        with pytest.raises(ArubaClientError, match=r"\(422\): query\.limit: Input should be less than or equal to 100"):
            client.get("/groups")

    def test_non_json_error_body_is_collapsed_to_one_line(self, client, httpx_mock):
        # A non-retryable status (403) with an HTML body, as a proxy or WAF would send it.
        httpx_mock.add_response(
            url=f"{UXI_BASE}/groups", status_code=403, text="<html>\n  <body>Denied</body>\n</html>"
        )

        with pytest.raises(
            ArubaClientError, match=r"^UXI GET /groups failed \(403\): <html> <body>Denied</body> </html>$"
        ):
            client.get("/groups")

    def test_non_json_success_body_raises(self, client, httpx_mock):
        httpx_mock.add_response(url=f"{UXI_BASE}/groups", text="ok")

        with pytest.raises(ArubaClientError, match=r"returned non-JSON \(200\)"):
            client.get("/groups")

    @pytest.mark.usefixtures("_no_sleep")
    def test_retries_rate_limit_then_succeeds(self, client, httpx_mock):
        httpx_mock.add_response(url=f"{UXI_BASE}/groups", status_code=429, json=ERROR_429)
        httpx_mock.add_response(url=f"{UXI_BASE}/groups", json=page([]))

        assert client.get("/groups") == page([])
        assert len(httpx_mock.get_requests()) == 2

    @pytest.mark.usefixtures("_no_sleep")
    def test_rate_limit_exhausted_maps_error(self, client, httpx_mock):
        for _ in range(3):
            httpx_mock.add_response(url=f"{UXI_BASE}/groups", status_code=429, json=ERROR_429)

        with pytest.raises(ArubaClientError, match=r"\(429 HPE_GL_ERROR_TOO_MANY_REQUESTS\)"):
            client.get("/groups")
        assert len(httpx_mock.get_requests()) == 3

    @pytest.mark.usefixtures("_no_sleep")
    def test_transport_error_is_wrapped(self, client, httpx_mock):
        for _ in range(3):
            httpx_mock.add_exception(httpx.ConnectError("boom"))

        with pytest.raises(ArubaClientError, match="UXI GET /groups failed after 3 attempts"):
            client.get("/groups")

    def test_repr_hides_token(self, client):
        assert FAKE_UXI_TOKEN not in repr(client)
        assert "eu-production" in repr(client)

    def test_unknown_region_raises(self):
        with pytest.raises(ValueError, match="Unknown UXI region 'eu'"):
            UxiClient(FAKE_UXI_TOKEN, region="eu")  # type: ignore[arg-type]


class TestIterItems:
    def test_follows_cursor_across_pages(self, client, httpx_mock):
        httpx_mock.add_response(url=f"{UXI_BASE}/groups?limit=100", json=page(GROUPS[:2], "cursor-2"))
        httpx_mock.add_response(url=f"{UXI_BASE}/groups?limit=100&next=cursor-2", json=page(GROUPS[2:]))

        rows = list(client.iter_items("/groups"))

        assert [row["id"] for row in rows] == [group["id"] for group in GROUPS]
        assert len(httpx_mock.get_requests()) == 2

    @pytest.mark.parametrize(
        "last_page", [page(GROUPS[:1], None), page(GROUPS[:1], ""), {"count": 1, "items": GROUPS[:1]}]
    )
    def test_stops_when_next_is_null_empty_or_missing(self, client, httpx_mock, last_page):
        httpx_mock.add_response(url=f"{UXI_BASE}/groups?limit=100", json=last_page)

        assert len(list(client.iter_items("/groups"))) == 1
        assert len(httpx_mock.get_requests()) == 1

    def test_only_first_page_ignores_cursor(self, client, httpx_mock):
        httpx_mock.add_response(url=f"{UXI_BASE}/groups?limit=2", json=page(GROUPS[:2], "cursor-2"))

        assert len(list(client.iter_items("/groups", page_size=2, only_first_page=True))) == 2
        assert len(httpx_mock.get_requests()) == 1

    def test_stops_on_page_without_items(self, client, httpx_mock):
        httpx_mock.add_response(url=f"{UXI_BASE}/groups?limit=100", json=page([], "cursor-2"))

        assert list(client.iter_items("/groups")) == []
        assert len(httpx_mock.get_requests()) == 1

    def test_stops_on_repeated_cursor(self, client, httpx_mock):
        httpx_mock.add_response(url=f"{UXI_BASE}/groups?limit=100", json=page(GROUPS[:1], "cursor-x"))
        httpx_mock.add_response(url=f"{UXI_BASE}/groups?limit=100&next=cursor-x", json=page(GROUPS[1:2], "cursor-x"))

        assert len(list(client.iter_items("/groups"))) == 2
        assert len(httpx_mock.get_requests()) == 2

    def test_stops_at_page_limit(self, client, httpx_mock, monkeypatch):
        monkeypatch.setattr(uxi_module, "_MAX_PAGES", 2)
        httpx_mock.add_response(url=f"{UXI_BASE}/groups?limit=100", json=page(GROUPS[:1], "c1"))
        httpx_mock.add_response(url=f"{UXI_BASE}/groups?limit=100&next=c1", json=page(GROUPS[1:2], "c2"))

        assert len(list(client.iter_items("/groups"))) == 2
        assert len(httpx_mock.get_requests()) == 2

    @pytest.mark.parametrize("page_size", [0, 101])
    def test_page_size_out_of_range_raises(self, client, httpx_mock, page_size):
        with pytest.raises(ValueError, match="page_size must be between 1 and 100"):
            list(client.iter_items("/groups", page_size=page_size))
        assert len(httpx_mock.get_requests()) == 0

    def test_extra_params_are_merged_with_limit(self, client, httpx_mock):
        httpx_mock.add_response(url=f"{UXI_BASE}/sensors?id={SENSOR_1}&limit=100", json=page(SENSORS[:1]))

        assert len(list(client.iter_items("/sensors", params={"id": SENSOR_1}))) == 1


class TestGetters:
    def test_get_groups_parses_registry(self, client, httpx_mock):
        httpx_mock.add_response(url=f"{UXI_BASE}/groups?limit=100", json=page(GROUPS))

        result = uxi.get_groups(client)
        registry = result.parsed()

        assert result.raw == GROUPS
        assert isinstance(registry, UxiGroupRegistry)
        assert registry.resolve(ORG_ID).parent_id == ""
        assert registry.resolve(BUILDING_ID).parent_id == CAMPUS_ID
        campus = registry.resolve(CAMPUS_ID)
        assert registry.subtree_ids(campus) == {CAMPUS_ID, BUILDING_ID}
        assert registry.subtree_ids(registry.resolve(BUILDING_ID)) == {BUILDING_ID}

    def test_get_sensors_with_id_filter(self, client, httpx_mock):
        httpx_mock.add_response(url=f"{UXI_BASE}/sensors?id={SENSOR_1}&limit=100", json=page(SENSORS[:1]))

        sensors = uxi.get_sensors(client, sensor_id=SENSOR_1).parsed()

        assert len(sensors) == 1
        assert isinstance(sensors[0], UxiSensor)
        assert sensors[0].serial == "SENSORSERIAL01"
        assert sensors[0].model == "UX-G6EC"
        assert sensors[0].address_note == ""  # null coerced to ""
        assert sensors[0].latitude is None

    def test_get_sensor_group_assignments_parses(self, client, httpx_mock):
        httpx_mock.add_response(url=f"{UXI_BASE}/sensor-group-assignments?limit=100", json=page(ASSIGNMENTS))

        assignments = uxi.get_sensor_group_assignments(client).parsed()

        assert isinstance(assignments[0], UxiSensorGroupAssignment)
        assert (assignments[0].group_id, assignments[0].sensor_id) == (CAMPUS_ID, SENSOR_1)

    def test_get_sensor_status_online(self, client, httpx_mock):
        httpx_mock.add_response(url=f"{UXI_BASE}/sensors/{SENSOR_1}/status", json=STATUS_OK)

        status = uxi.get_sensor_status(client, SENSOR_1).parsed()

        assert isinstance(status, UxiSensorStatus)
        assert status.is_online is True
        assert status.issues == []

    def test_get_sensor_status_with_issue(self, client, httpx_mock):
        httpx_mock.add_response(url=f"{UXI_BASE}/sensors/{SENSOR_2}/status", json=STATUS_WITH_ISSUE)

        status = uxi.get_sensor_status(client, SENSOR_2).parsed()

        assert status.is_online is False
        assert status.is_testing is None
        issue = status.issues[0]
        assert (issue.code, issue.severity, issue.status) == ("EXTERNAL_SSL_ERROR", "ERROR", "CONFIRMED")
        assert issue.incident_id == ""
        assert issue.context["networkName"] == "demo-ssid"

    def test_get_sensor_status_not_found(self, client, httpx_mock):
        not_found = {
            "debugId": "dbg-0003",
            "errorCode": "HPE_GL_ERROR_NOT_FOUND",
            "httpStatusCode": 404,
            "message": "No such sensor",
        }
        httpx_mock.add_response(url=re.compile(r".*/sensors/.*/status"), status_code=404, json=not_found)

        with pytest.raises(ArubaClientError, match=r"\(404 HPE_GL_ERROR_NOT_FOUND\)"):
            uxi.get_sensor_status(client, "00000000-0000-4000-8000-000000000999")


class TestFindGroup:
    registry = UxiGroupRegistry.from_raw(GROUPS)

    def test_exact_match(self):
        assert uxi.find_group(self.registry, "Example Campus").id == CAMPUS_ID

    def test_not_found_lists_known_groups(self):
        with pytest.raises(
            UxiGroupNotFoundError, match="UXI group 'Nowhere' not found. Known groups: .*'Example Campus'"
        ):
            uxi.find_group(self.registry, "Nowhere")

    def test_ambiguous_name_lists_paths(self):
        with pytest.raises(
            ArubaClientError, match=r"ambiguous: \['g0000001.g0000002.g0000003', 'g0000001.g0000004.g0000005'\]"
        ):
            uxi.find_group(self.registry, "Building A")

    def test_match_is_case_sensitive(self):
        with pytest.raises(UxiGroupNotFoundError):
            uxi.find_group(self.registry, "example campus")


class TestGetGroupSensors:
    def test_filters_assignments_then_sensors(self, client, httpx_mock):
        httpx_mock.add_response(url=f"{UXI_BASE}/sensor-group-assignments?limit=100", json=page(ASSIGNMENTS))
        httpx_mock.add_response(url=f"{UXI_BASE}/sensors?limit=100", json=page(SENSORS))

        result = uxi.get_group_sensors(client, {CAMPUS_ID})

        assert result.raw == SENSORS[:1]
        assert [sensor.serial for sensor in result.parsed()] == ["SENSORSERIAL01"]
        assert len(httpx_mock.get_requests()) == 2

    def test_subtree_includes_child_group_sensor(self, client, httpx_mock):
        httpx_mock.add_response(url=f"{UXI_BASE}/sensor-group-assignments?limit=100", json=page(ASSIGNMENTS))
        httpx_mock.add_response(url=f"{UXI_BASE}/sensors?limit=100", json=page(SENSORS))
        registry = UxiGroupRegistry.from_raw(GROUPS)

        sensors = uxi.get_group_sensors(client, registry.subtree_ids(registry.resolve(CAMPUS_ID))).parsed()

        assert [sensor.serial for sensor in sensors] == ["SENSORSERIAL01", "SENSORSERIAL02"]

    def test_no_assignments_skips_sensor_fetch(self, client, httpx_mock):
        httpx_mock.add_response(url=f"{UXI_BASE}/sensor-group-assignments?limit=100", json=page(ASSIGNMENTS))

        result = uxi.get_group_sensors(client, {"00000000-0000-4000-8000-000000000777"})

        assert result.raw == []
        assert result.parsed() == []
        assert len(httpx_mock.get_requests()) == 1

    def test_assignment_without_sensor_row_is_skipped(self, client, httpx_mock):
        httpx_mock.add_response(url=f"{UXI_BASE}/sensor-group-assignments?limit=100", json=page(ASSIGNMENTS))
        httpx_mock.add_response(url=f"{UXI_BASE}/sensors?limit=100", json=page(SENSORS[1:]))  # sensor 1 vanished

        sensors = uxi.get_group_sensors(client, {CAMPUS_ID, BUILDING_ID}).parsed()

        assert [sensor.serial for sensor in sensors] == ["SENSORSERIAL02"]
