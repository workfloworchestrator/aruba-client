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

from aruba_client import gateways
from aruba_client.schema import Gateway, GatewayPort

GATEWAYS_MODULE = "aruba_client.gateways"


class TestGetGateways:
    def test_list_parses_to_gateway(self, monkeypatch):
        mock = Mock(return_value=[{"serialNumber": "GW1", "deviceName": "gw-01"}])
        monkeypatch.setattr(f"{GATEWAYS_MODULE}.MonitoringGateways.get_all_gateways", mock)

        result = gateways.get_gateways(Mock())

        assert result.raw == [{"serialNumber": "GW1", "deviceName": "gw-01"}]
        parsed = result.parsed()
        assert isinstance(parsed[0], Gateway)
        assert parsed[0].serial == "GW1"


class TestGetGatewayDetail:
    def test_detail_parses_single_gateway(self, monkeypatch):
        # Gateways carry their IP under ``ipAddress`` (not ``ipv4``).
        mock = Mock(return_value={"serialNumber": "GW1", "deviceName": "gw-01", "ipAddress": "10.0.0.1"})
        monkeypatch.setattr(f"{GATEWAYS_MODULE}.MonitoringGateways.get_gateway_details", mock)

        gateway = gateways.get_gateway_detail(Mock(), "GW1").parsed()

        assert isinstance(gateway, Gateway)
        assert gateway.ipv4 == "10.0.0.1"


class TestGatewaySubResources:
    def test_uplinks_unwrap_items(self, monkeypatch):
        mock = Mock(return_value={"items": [{"linkTag": "wan0", "status": "up"}], "total": 1})
        monkeypatch.setattr(f"{GATEWAYS_MODULE}.MonitoringGateways.get_gateway_uplinks", mock)

        # Uplinks stay raw (unmodelled) — no non-empty sample to model against yet.
        assert gateways.get_gateway_uplinks(Mock(), "GW1") == [{"linkTag": "wan0", "status": "up"}]

    def test_ports_passes_filters_and_parses(self, monkeypatch):
        mock = Mock(return_value=[{"name": "GE 0/0/0", "operState": "Down", "totalPackets": 0}])
        monkeypatch.setattr(f"{GATEWAYS_MODULE}.MonitoringGateways.get_all_gateway_ports", mock)

        result = gateways.get_gateway_ports(Mock(), "GW1", sort="name")

        assert result.raw == [{"name": "GE 0/0/0", "operState": "Down", "totalPackets": 0}]
        parsed = result.parsed()
        assert isinstance(parsed[0], GatewayPort)
        assert parsed[0].name == "GE 0/0/0"
        assert parsed[0].oper_state == "Down"
        _, kwargs = mock.call_args
        assert kwargs["sort"] == "name"
