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

from aruba_client import switches
from aruba_client.schema import Switch, SwitchDetail, SwitchInterface, SwitchVlan

SWITCHES_MODULE = "aruba_client.switches"


class TestGetSwitches:
    def test_list_parses_to_switch(self, monkeypatch):
        mock = Mock(return_value=[{"serialNumber": "SW1", "deviceName": "switch-01"}])
        monkeypatch.setattr(f"{SWITCHES_MODULE}.MonitoringSwitches.get_all_switches", mock)

        result = switches.get_switches(Mock(), filter_str="status eq ONLINE")

        assert result.raw == [{"serialNumber": "SW1", "deviceName": "switch-01"}]
        parsed = result.parsed()
        assert isinstance(parsed[0], Switch)
        assert parsed[0].serial == "SW1"
        _, kwargs = mock.call_args
        assert kwargs["filter_str"] == "status eq ONLINE"


class TestGetSwitchDetail:
    def test_detail_parses_single_switch(self, monkeypatch):
        mock = Mock(return_value={"serialNumber": "SW1", "deviceName": "switch-01", "stackId": "st1", "health": "Good"})
        monkeypatch.setattr(f"{SWITCHES_MODULE}.MonitoringSwitches.get_switch_details", mock)

        result = switches.get_switch_detail(Mock(), "SW1")

        switch = result.parsed()
        assert isinstance(switch, SwitchDetail)
        assert switch.stack_id == "st1"
        assert switch.health == "Good"


class TestSwitchSubResources:
    def test_interfaces_unwrap_and_parse(self, monkeypatch):
        mock = Mock(return_value={"items": [{"name": "1/1/1", "status": "Connected", "uplink": True}], "total": 1})
        monkeypatch.setattr(f"{SWITCHES_MODULE}.MonitoringSwitches.get_switch_interfaces", mock)

        result = switches.get_switch_interfaces(Mock(), "SW1")

        # .raw is the untouched payload; .parsed() yields typed SwitchInterface rows.
        assert result.raw == [{"name": "1/1/1", "status": "Connected", "uplink": True}]
        parsed = result.parsed()
        assert isinstance(parsed[0], SwitchInterface)
        assert parsed[0].name == "1/1/1"
        assert parsed[0].uplink is True

    def test_vlans_unwrap_and_parse(self, monkeypatch):
        mock = Mock(return_value={"items": [{"id": "10", "name": "VLAN10"}], "total": 1})
        monkeypatch.setattr(f"{SWITCHES_MODULE}.MonitoringSwitches.get_switch_vlans", mock)

        result = switches.get_switch_vlans(Mock(), "SW1")

        assert result.raw == [{"id": "10", "name": "VLAN10"}]
        parsed = result.parsed()
        assert isinstance(parsed[0], SwitchVlan)
        assert parsed[0].id == "10"
