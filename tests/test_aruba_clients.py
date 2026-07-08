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

from aruba_client import clients
from aruba_client.schema import Client

CLIENTS_MODULE = "aruba_client.clients"


class TestGetClients:
    def test_passes_site_and_serial(self, monkeypatch):
        mock = Mock(return_value=[{"macAddress": "aa:bb", "clientName": "laptop"}])
        monkeypatch.setattr(f"{CLIENTS_MODULE}.Clients.get_all_clients", mock)

        result = clients.get_clients(Mock(), site_id="s1", serial="SN1")

        assert result.raw == [{"macAddress": "aa:bb", "clientName": "laptop"}]
        parsed = result.parsed()
        assert isinstance(parsed[0], Client)
        assert parsed[0].mac == "aa:bb"
        _, kwargs = mock.call_args
        assert kwargs["site_id"] == "s1"
        assert kwargs["serial_number"] == "SN1"


class TestGetWirelessClients:
    def test_delegates_to_wireless_endpoint(self, monkeypatch):
        mock = Mock(return_value=[{"macAddress": "aa:bb", "clientConnectionType": "Wireless"}])
        monkeypatch.setattr(f"{CLIENTS_MODULE}.Clients.get_wireless_clients", mock)

        result = clients.get_wireless_clients(Mock(), site_id="s1")

        assert result.parsed()[0].connection_type == "Wireless"
        _, kwargs = mock.call_args
        assert kwargs["site_id"] == "s1"


class TestGetClientsForDevice:
    def test_uses_associated_device_endpoint(self, monkeypatch):
        mock = Mock(return_value=[{"macAddress": "aa:bb"}])
        monkeypatch.setattr(f"{CLIENTS_MODULE}.Clients.get_clients_associated_device", mock)

        result = clients.get_clients_for_device(Mock(), "SN1")

        assert result.parsed()[0].mac == "aa:bb"
        args, _ = mock.call_args
        assert args[1] == "SN1"


class TestGetClientDetail:
    def test_returns_single_client(self, monkeypatch):
        mock = Mock(return_value={"macAddress": "aa:bb", "clientName": "laptop", "snr": 40})
        monkeypatch.setattr(f"{CLIENTS_MODULE}.Clients.get_client_details", mock)

        result = clients.get_client_detail(Mock(), "aa:bb")

        client = result.parsed()
        assert isinstance(client, Client)
        assert client.name == "laptop"
        assert client.snr == 40
