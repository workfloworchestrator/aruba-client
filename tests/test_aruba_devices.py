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

from unittest.mock import Mock

from aruba_client import devices
from aruba_client.schema import AccessPoint, AccessPointDetail, Device, InventoryDevice, Port, Radio, Wlan

DEVICES_MODULE = "aruba_client.devices"

# A trimmed but representative get_ap_details payload.
AP_DETAIL_RAW = {
    "serialNumber": "APSERIAL01",
    "deviceName": "demo-ap-01",
    "model": "AP-515",
    "macAddress": "00:11:22:33:44:55",
    "manufacturer": "HPE",
    "status": "ONLINE",
    "siteId": "site-001",
    "firmwareVersion": "10.7.0.0",
    "countryCode": "NL",
    "uptimeInMillis": 123456789,
    "lastSeenAt": "2026-06-12T18:00:00Z",
    "lastRebootReason": "User reboot",
    "negotiatedPower": 23,
    "radios": [{"radioNumber": 0, "band": "2.4GHz"}],
    "ports": [{"id": "0"}],
    "wlans": [{"essid": "eduroam"}],
    "apStats": {"clientCount": 4},
}


class TestGetAccessPoints:
    def test_no_filter(self, monkeypatch):
        mock = Mock(return_value=[{"serialNumber": "SN1"}])
        monkeypatch.setattr(f"{DEVICES_MODULE}.MonitoringAPs.get_all_aps", mock)

        result = devices.get_access_points(Mock())

        assert result.raw == [{"serialNumber": "SN1"}]
        parsed = result.parsed()
        assert isinstance(parsed[0], AccessPoint)
        assert parsed[0].serial == "SN1"
        _, kwargs = mock.call_args
        assert kwargs["filter_str"] is None

    def test_site_id_becomes_filter(self, monkeypatch):
        mock = Mock(return_value=[])
        monkeypatch.setattr(f"{DEVICES_MODULE}.MonitoringAPs.get_all_aps", mock)

        devices.get_access_points(Mock(), site_id="site-001")

        _, kwargs = mock.call_args
        assert kwargs["filter_str"] == "siteId eq site-001"

    def test_site_id_is_anded_with_user_filter(self, monkeypatch):
        mock = Mock(return_value=[])
        monkeypatch.setattr(f"{DEVICES_MODULE}.MonitoringAPs.get_all_aps", mock)

        devices.get_access_points(Mock(), site_id="site-001", filter_str="status eq ONLINE")

        _, kwargs = mock.call_args
        assert kwargs["filter_str"] == "status eq ONLINE and siteId eq site-001"


class TestGetAccessPointDetail:
    def test_parsed_returns_normalized_model(self, monkeypatch):
        monkeypatch.setattr(f"{DEVICES_MODULE}.MonitoringAPs.get_ap_details", Mock(return_value=AP_DETAIL_RAW))

        detail = devices.get_access_point_detail(Mock(), "APSERIAL01").parsed()

        assert isinstance(detail, AccessPointDetail)
        assert detail.serial == "APSERIAL01"
        assert detail.mac == "00:11:22:33:44:55"
        assert detail.uptime_millis == 123456789
        assert detail.negotiated_power == "23"
        assert detail.radios == [{"radioNumber": 0, "band": "2.4GHz"}]
        # apStats is not promoted to an attribute but remains reachable via raw.
        assert detail.raw["apStats"] == {"clientCount": 4}

    def test_raw_passthrough(self, monkeypatch):
        monkeypatch.setattr(f"{DEVICES_MODULE}.MonitoringAPs.get_ap_details", Mock(return_value=AP_DETAIL_RAW))
        assert devices.get_access_point_detail(Mock(), "APSERIAL01").raw == AP_DETAIL_RAW


class TestSubResourceWrappers:
    def test_radios_unwraps_items_and_parses(self, monkeypatch):
        monkeypatch.setattr(
            f"{DEVICES_MODULE}.MonitoringAPs.get_ap_radios",
            Mock(return_value={"items": [{"radioNumber": 0, "band": "2.4 GHz"}], "total": 1, "count": 1}),
        )
        result = devices.get_access_point_radios(Mock(), "SN1")
        assert result.raw == [{"radioNumber": 0, "band": "2.4 GHz"}]
        assert isinstance(result.parsed()[0], Radio)
        assert result.parsed()[0].radio_number == 0

    def test_ports_unwraps_items_and_parses(self, monkeypatch):
        monkeypatch.setattr(
            f"{DEVICES_MODULE}.MonitoringAPs.get_ap_ports",
            Mock(return_value={"items": [{"name": "eth0", "portIndex": 0}], "total": 1}),
        )
        result = devices.get_access_point_ports(Mock(), "SN1")
        assert result.raw == [{"name": "eth0", "portIndex": 0}]
        assert isinstance(result.parsed()[0], Port)

    def test_wlans_unwraps_items_and_parses(self, monkeypatch):
        monkeypatch.setattr(
            f"{DEVICES_MODULE}.MonitoringAPs.get_ap_wlans",
            Mock(return_value={"items": [{"wlanName": "eduroam"}], "total": 1}),
        )
        result = devices.get_access_point_wlans(Mock(), "SN1")
        assert result.raw == [{"wlanName": "eduroam"}]
        parsed = result.parsed()
        assert isinstance(parsed[0], Wlan)
        assert parsed[0].wlan_name == "eduroam"


class TestFleetWlansAndRadios:
    def test_get_radios_combines_site_filter(self, monkeypatch):
        mock = Mock(return_value=[{"radioNumber": 0, "band": "5GHz"}])
        monkeypatch.setattr(f"{DEVICES_MODULE}.MonitoringAPs.get_all_radios", mock)

        result = devices.get_radios(Mock(), site_id="site-001")

        assert isinstance(result.parsed()[0], Radio)
        _, kwargs = mock.call_args
        assert kwargs["filter_str"] == "siteId eq site-001"

    def test_get_wlans_passes_site_and_serial(self, monkeypatch):
        mock = Mock(return_value=[{"id": "w1", "wlanName": "eduroam", "type": "EMPLOYEE"}])
        monkeypatch.setattr(f"{DEVICES_MODULE}.WLAN.get_all_wlans", mock)

        result = devices.get_wlans(Mock(), site_id="site-001", serial="SN1")

        parsed = result.parsed()
        assert isinstance(parsed[0], Wlan)
        assert parsed[0].id == "w1"
        assert parsed[0].type == "EMPLOYEE"
        _, kwargs = mock.call_args
        assert kwargs["site_id"] == "site-001"
        assert kwargs["serial_number"] == "SN1"


class TestDeviceInventory:
    def test_get_devices(self, monkeypatch):
        mock = Mock(return_value=[{"serialNumber": "SN1", "deviceType": "ACCESS_POINT"}])
        monkeypatch.setattr(f"{DEVICES_MODULE}.MonitoringDevices.get_all_devices", mock)

        result = devices.get_devices(Mock())

        assert result.raw == [{"serialNumber": "SN1", "deviceType": "ACCESS_POINT"}]
        parsed = result.parsed()
        assert isinstance(parsed[0], Device)
        assert parsed[0].device_type == "ACCESS_POINT"

    def test_get_device_inventory_passes_site_assigned(self, monkeypatch):
        mock = Mock(return_value=[{"serialNumber": "SN1", "isProvisioned": False}])
        monkeypatch.setattr(f"{DEVICES_MODULE}.MonitoringDevices.get_all_device_inventory", mock)

        result = devices.get_device_inventory(Mock(), site_assigned="UNASSIGNED")

        assert result.raw == [{"serialNumber": "SN1", "isProvisioned": False}]
        parsed = result.parsed()
        assert isinstance(parsed[0], InventoryDevice)
        assert parsed[0].is_provisioned is False
        _, kwargs = mock.call_args
        assert kwargs["site_assigned"] == "UNASSIGNED"
