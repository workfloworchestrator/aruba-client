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

"""Read-only wrappers around the Aruba Central ``network-monitoring/v1/switches`` API.

Every getter returns a :class:`~aruba_client.schema.CentralResponse`
(``.parsed()`` for the typed model, ``.raw`` for the untouched payload): the list
yields :class:`~aruba_client.schema.Switch`, detail yields
:class:`~aruba_client.schema.SwitchDetail`, and the per-switch interface /
VLAN helpers yield :class:`~aruba_client.schema.SwitchInterface` /
:class:`~aruba_client.schema.SwitchVlan`. Trend endpoints are out of scope.

Get a ``conn`` from :func:`aruba_client.client.get_central_client`.
"""

from typing import Any

import structlog
from pycentral import NewCentralBase
from pycentral.new_monitoring import MonitoringSwitches

from aruba_client.schema import CentralResponse, Switch, SwitchDetail, SwitchInterface, SwitchVlan

logger = structlog.get_logger(__name__)


def _items(response: Any) -> list[dict]:
    if isinstance(response, dict):
        return response.get("items", [])
    return response or []


def get_switches(
    conn: NewCentralBase,
    *,
    filter_str: str | None = None,
    sort: str | None = None,
) -> CentralResponse[list[dict], list[Switch]]:
    """List switches (``network-monitoring/v1/switches``) — see ``Switch``."""
    rows = MonitoringSwitches.get_all_switches(conn, filter_str=filter_str, sort=sort)
    return CentralResponse(rows, Switch.list_from_raw)


def get_switch_detail(conn: NewCentralBase, serial: str) -> CentralResponse[dict, SwitchDetail]:
    """Detail for one switch / stack (``network-monitoring/v1/switches/{serial}``) — see ``SwitchDetail``."""
    return CentralResponse(MonitoringSwitches.get_switch_details(conn, serial), SwitchDetail.from_raw)


def get_switch_interfaces(conn: NewCentralBase, serial: str) -> CentralResponse[list[dict], list[SwitchInterface]]:
    """Interfaces of one switch (``.../switches/{serial}/interfaces``) — see ``SwitchInterface``."""
    return CentralResponse(
        _items(MonitoringSwitches.get_switch_interfaces(conn, serial)), SwitchInterface.list_from_raw
    )


def get_switch_vlans(conn: NewCentralBase, serial: str) -> CentralResponse[list[dict], list[SwitchVlan]]:
    """VLANs of one switch (``.../switches/{serial}/vlans``) — see ``SwitchVlan``."""
    return CentralResponse(_items(MonitoringSwitches.get_switch_vlans(conn, serial)), SwitchVlan.list_from_raw)
