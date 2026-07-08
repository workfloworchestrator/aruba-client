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

"""Read-only wrappers around the Aruba Central ``network-monitoring/v1/gateways`` API.

The list/detail getters return a :class:`~aruba_client.schema.CentralResponse`
of :class:`~aruba_client.schema.Gateway` (``.parsed()`` / ``.raw``); ports
yield :class:`~aruba_client.schema.GatewayPort`. The per-gateway uplink helper
still returns the raw ``list[dict]`` — that shape isn't modelled yet (no non-empty
sample observed). The many trend/cluster endpoints are intentionally out of scope.

Get a ``conn`` from :func:`aruba_client.client.get_central_client`.
"""

from typing import Any

import structlog
from pycentral import NewCentralBase
from pycentral.new_monitoring import MonitoringGateways

from aruba_client.schema import CentralResponse, Gateway, GatewayPort

logger = structlog.get_logger(__name__)


def _items(response: Any) -> list[dict]:
    if isinstance(response, dict):
        return response.get("items", [])
    return response or []


def get_gateways(
    conn: NewCentralBase,
    *,
    filter_str: str | None = None,
    sort: str | None = None,
) -> CentralResponse[list[dict], list[Gateway]]:
    """List gateways (``network-monitoring/v1/gateways``) — see ``Gateway``."""
    rows = MonitoringGateways.get_all_gateways(conn, filter_str=filter_str, sort=sort)
    return CentralResponse(rows, Gateway.list_from_raw)


def get_gateway_detail(conn: NewCentralBase, serial: str) -> CentralResponse[dict, Gateway]:
    """Detail for one gateway (``network-monitoring/v1/gateways/{serial}``) — see ``Gateway``."""
    return CentralResponse(MonitoringGateways.get_gateway_details(conn, serial), Gateway.from_raw)


def get_gateway_uplinks(conn: NewCentralBase, serial: str) -> list[dict]:
    """Uplinks of one gateway (``.../gateways/{serial}/uplinks``), returned raw (unmodelled).

    Left raw because no gateway observed so far reports any uplinks; model it
    once a non-empty sample is available.
    """
    return _items(MonitoringGateways.get_gateway_uplinks(conn, serial))


def get_gateway_ports(
    conn: NewCentralBase,
    serial: str,
    *,
    filter_str: str | None = None,
    sort: str | None = None,
) -> CentralResponse[list[dict], list[GatewayPort]]:
    """Ports of one gateway (``.../gateways/{serial}/ports``) — see ``GatewayPort``."""
    rows = _items(MonitoringGateways.get_all_gateway_ports(conn, serial, filter_str=filter_str, sort=sort))
    return CentralResponse(rows, GatewayPort.list_from_raw)
