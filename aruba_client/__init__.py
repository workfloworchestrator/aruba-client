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

from aruba_client.client import (
    ArubaClientError,
    get_central_client,
    get_msp_tenant_names,
    get_new_central_aps,
    get_new_central_site_configs,
    get_new_central_sites,
)
from aruba_client.config import ArubaConfig
from aruba_client.schema import (
    AccessPoint,
    AccessPointDetail,
    CentralResponse,
    Client,
    Device,
    DeviceHealth,
    Gateway,
    GatewayPort,
    InventoryDevice,
    Port,
    Radio,
    Site,
    SiteConfig,
    SiteRegistry,
    Switch,
    SwitchDetail,
    SwitchInterface,
    SwitchVlan,
    Wlan,
)

__all__ = [
    "ArubaClientError",
    "ArubaConfig",
    "CentralResponse",
    "get_central_client",
    "get_msp_tenant_names",
    "get_new_central_aps",
    "get_new_central_site_configs",
    "get_new_central_sites",
    "AccessPoint",
    "AccessPointDetail",
    "Client",
    "Device",
    "DeviceHealth",
    "Gateway",
    "GatewayPort",
    "InventoryDevice",
    "Port",
    "Radio",
    "Site",
    "SiteConfig",
    "SiteRegistry",
    "Switch",
    "SwitchDetail",
    "SwitchInterface",
    "SwitchVlan",
    "Wlan",
]
