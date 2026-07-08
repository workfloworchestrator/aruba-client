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

import pytest

from aruba_client.schema import (
    AccessPoint,
    CentralResponse,
    Client,
    Gateway,
    GatewayPort,
    SiteConfig,
    SiteRegistry,
    Switch,
    SwitchDetail,
    SwitchInterface,
    SwitchVlan,
    Wlan,
)


class TestCentralResponse:
    def test_raw_returns_input_untouched(self):
        rows = [{"id": "s1", "siteName": "Site 1"}]
        resp = CentralResponse(rows, SiteRegistry.from_raw)

        assert resp.raw is rows

    def test_parsed_validates_and_memoizes(self):
        calls = []

        def parser(rows):
            calls.append(rows)
            return SiteRegistry.from_raw(rows)

        resp = CentralResponse([{"id": "s1", "siteName": "Site 1"}], parser)

        first = resp.parsed()
        second = resp.parsed()

        assert isinstance(first, SiteRegistry)
        assert first is second  # memoized
        assert len(calls) == 1  # parser ran exactly once

    def test_parsed_raises_on_bad_payload_but_raw_still_available(self):
        # A site dict missing the required "id" (e.g. the API renamed the field) — parsing blows up...
        bad = [{"siteName": "no id here"}]
        resp = CentralResponse(bad, SiteRegistry.from_raw)

        with pytest.raises(KeyError):
            resp.parsed()

        # ...while the escape hatch still hands back the untouched payload.
        assert resp.raw == bad


class TestAccessPointModel:
    def test_from_raw_promotes_and_keeps_raw(self):
        raw = {
            "serialNumber": "SN1",
            "deviceName": "ap1",
            "model": "AP-515",
            "siteName": "Site",
            "uptimeInMillis": 123,
            "lastSeenAt": None,
            "extraFieldFromFutureApi": "ignored-but-kept-in-raw",
        }
        ap = AccessPoint.from_raw(raw)

        assert ap.serial == "SN1"
        assert ap.uptime_millis == 123
        assert ap.last_seen_at == ""  # None coerced to ""
        assert ap.raw["extraFieldFromFutureApi"] == "ignored-but-kept-in-raw"


class TestSiteConfigModel:
    def test_from_raw_maps_address_fields(self):
        # Trimmed representative shape from network-config/v1alpha1/sites (note: no site "name").
        raw = {
            "id": "s1",
            "address": "Voorbeeldstraat 1",
            "city": "Amsterdam",
            "zipcode": "1234AB",
            "country": "Netherlands",
            "collectionName": "Example Campus",
            "deviceCount": 12,
            "image": "ignored-but-kept-out-of-model",
        }
        cfg = SiteConfig.from_raw(raw)

        assert cfg.id == "s1"
        assert cfg.address == "Voorbeeldstraat 1"
        assert cfg.city == "Amsterdam"
        assert cfg.zipcode == "1234AB"
        assert cfg.collection_name == "Example Campus"
        assert cfg.device_count == 12


class TestClientModel:
    def test_from_raw_promotes_and_keeps_raw(self):
        # Trimmed representative shape from network-monitoring/v1/clients.
        raw = {
            "macAddress": "aa:bb:cc:dd:ee:ff",
            "clientName": "laptop-01",
            "hostName": "laptop-01.local",
            "ipv4": "10.0.0.5",
            "clientConnectionType": "Wireless",
            "status": "CONNECTED",
            "siteId": "s1",
            "userName": "user@example.org",
            "clientOperatingSystem": "macOS",
            "snr": 42,
            "wirelessBand": "5GHz",
            "wlanName": "eduroam",
            "vlanId": "100",
            "futureField": "ignored-but-kept-in-raw",
        }
        client = Client.from_raw(raw)

        assert client.mac == "aa:bb:cc:dd:ee:ff"
        assert client.name == "laptop-01"
        assert client.connection_type == "Wireless"
        assert client.snr == 42
        assert client.wlan_name == "eduroam"
        assert client.vlan_id == "100"  # int-ish field coerced to str
        assert client.raw["futureField"] == "ignored-but-kept-in-raw"

    def test_missing_fields_default_empty(self):
        client = Client.from_raw({"macAddress": "aa:bb:cc:dd:ee:ff"})
        assert client.name == ""
        assert client.snr is None


class TestWlanModelFleetFields:
    def test_fleet_wlan_has_id_and_type(self):
        # Network-wide wlans carry id/type that the per-AP shape omits.
        wlan = Wlan.from_raw({"id": "w1", "wlanName": "eduroam", "type": "EMPLOYEE", "band": "5GHz"})
        assert wlan.id == "w1"
        assert wlan.type == "EMPLOYEE"
        assert wlan.wlan_name == "eduroam"

    def test_per_ap_wlan_without_id_type(self):
        wlan = Wlan.from_raw({"wlanName": "eduroam"})
        assert wlan.id == ""
        assert wlan.type == ""


class TestSwitchAndGatewayModels:
    def test_switch_from_raw(self):
        # Trimmed representative shape from network-monitoring/v1/switches.
        raw = {
            "serialNumber": "SWSERIAL01",
            "deviceName": "demo-sw-01",
            "model": "CX-6100",
            "status": "Online",
            "siteId": "s1",
            "ipv4": "10.0.10.2",
            "publicIp": "198.51.100.26",
            "jNumber": "JL675A",
            "stackId": None,
            "stackMemberId": None,
            "switchType": "cx",
            "switchRole": "Standalone",
        }
        switch = Switch.from_raw(raw)
        assert switch.serial == "SWSERIAL01"
        assert switch.name == "demo-sw-01"
        assert switch.ipv4 == "10.0.10.2"
        assert switch.public_ip == "198.51.100.26"
        assert switch.j_number == "JL675A"
        assert switch.switch_type == "cx"
        # role comes from ``switchRole`` (switches have no ``role`` key).
        assert switch.role == "Standalone"

    def test_switch_detail_from_raw(self):
        # Detail adds health/config fields the list omits.
        raw = {
            "serialNumber": "SWSERIAL01",
            "deviceName": "demo-sw-01",
            "switchRole": "Standalone",
            "configStatus": "Synchronized",
            "manufacturer": "HPE ANW",
            "health": "Good",
            "healthReasons": {"poorReasons": [], "fairReasons": []},
            "lastRestartReason": "Reboot requested by user",
            "lastConfigChange": 1774390961000,
            "switchLinkType": None,
        }
        detail = SwitchDetail.from_raw(raw)
        assert detail.config_status == "Synchronized"
        assert detail.manufacturer == "HPE ANW"
        assert detail.health == "Good"
        assert detail.health_reasons == {"poorReasons": [], "fairReasons": []}
        assert detail.last_config_change == 1774390961000
        assert detail.role == "Standalone"

    def test_switch_interface_from_raw(self):
        # Trimmed representative shape from .../switches/{serial}/interfaces.
        raw = {
            "id": "1/1/1",
            "name": "1/1/1",
            "index": 1,
            "portIndex": 1,
            "adminStatus": "Up",
            "operStatus": "Up",
            "speed": 1000000000,
            "mtu": 1500,
            "vlanMode": "Trunk",
            "nativeVlan": 1,
            "allowedVlans": ["1", "20-21", ""],
            "allowedVlanIds": [1, 20, 21],
            "uplink": False,
            "status": "Connected",
        }
        iface = SwitchInterface.from_raw(raw)
        assert iface.id == "1/1/1"
        assert iface.speed == 1000000000
        assert iface.mtu == 1500
        assert iface.native_vlan == 1
        assert iface.uplink is False
        # empty strings are dropped from allowedVlans; ids stay typed ints.
        assert iface.allowed_vlans == ["1", "20-21"]
        assert iface.allowed_vlan_ids == [1, 20, 21]

    def test_switch_vlan_from_raw(self):
        # Trimmed representative shape from .../switches/{serial}/vlans (untaggedPorts may be null).
        raw = {
            "id": "1",
            "name": "DEFAULT_VLAN_1",
            "type": "Default",
            "status": "Up",
            "voice": "Disabled",
            "taggedPorts": ["1/1/49", "lag1"],
            "untaggedPorts": None,
            "interfaces": ["1/1/2", "lag1"],
        }
        vlan = SwitchVlan.from_raw(raw)
        assert vlan.id == "1"
        assert vlan.name == "DEFAULT_VLAN_1"
        assert vlan.tagged_ports == ["1/1/49", "lag1"]
        assert vlan.untagged_ports == []
        assert vlan.interfaces == ["1/1/2", "lag1"]

    def test_gateway_from_raw(self):
        # Trimmed representative shape from network-monitoring/v1/gateways (IP under ``ipAddress``).
        raw = {
            "serialNumber": "GWSERIAL01",
            "deviceName": "demo-gw-01",
            "model": "A9240",
            "status": "Online",
            "ipAddress": "203.0.113.7",
            "macRange": "00:11:22:33:44:00-00:11:22:33:44:3f",
            "role": "Member",
            "mode": None,
            "clusterName": "auto_gwcluster_1_0",
            "deviceFunction": "Unspecified",
            "rebootReason": "AC power cycle",
            "cpuUtilization": 5,
            "memoryUtilization": 19,
        }
        gateway = Gateway.from_raw(raw)
        assert gateway.serial == "GWSERIAL01"
        assert gateway.name == "demo-gw-01"
        # ipv4 comes from ``ipAddress`` (gateways have no ``ipv4`` key).
        assert gateway.ipv4 == "203.0.113.7"
        assert gateway.mac_range == "00:11:22:33:44:00-00:11:22:33:44:3f"
        assert gateway.cluster_name == "auto_gwcluster_1_0"
        assert gateway.device_function == "Unspecified"
        assert gateway.reboot_reason == "AC power cycle"
        assert gateway.cpu_utilization == 5
        assert gateway.memory_utilization == 19

    def test_gateway_port_from_raw(self):
        # Trimmed representative shape from .../gateways/{serial}/ports.
        raw = {
            "id": "GWSERIAL01/ports/GE 0/0/0",
            "name": "GE 0/0/0",
            "portNumber": "0",
            "portType": "Access",
            "adminState": "Enabled",
            "operState": "Down",
            "health": "Unknown",
            "healthReasons": [],
            "vlan": "1",
            "mtu": "1500 bytes",
            "speed": "Auto",
            "duplex": "Auto",
            "macAddress": "00:11:22:33:44:0a",
            "totalPackets": 0,
            "crcErrors": 0,
            "usage": {"total": 0, "received": 0, "sent": 0},
            "throughput": {"received": 0, "sent": 0},
        }
        port = GatewayPort.from_raw(raw)
        assert port.name == "GE 0/0/0"
        assert port.oper_state == "Down"
        assert port.mtu == "1500 bytes"
        assert port.mac == "00:11:22:33:44:0a"
        assert port.total_packets == 0
        assert port.usage == {"total": 0, "received": 0, "sent": 0}
