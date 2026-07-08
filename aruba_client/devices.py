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

"""Read-only wrappers around the Aruba Central ``network-monitoring/v1`` device APIs.

Each function delegates to pycentral (``MonitoringAPs`` / ``MonitoringDevices`` —
cursor pagination, payload validation, 429 retry inside ``NewCentralBase.command()``)
and returns a :class:`~aruba_client.schema.CentralResponse`: call ``.parsed()``
for the typed model or ``.raw`` for the untouched payload. Response shapes are
documented by the models in :mod:`aruba_client.schema`.

Get a ``conn`` from :func:`aruba_client.client.get_central_client`.
"""

from typing import Any

import structlog
from pycentral import NewCentralBase
from pycentral.new_monitoring import WLAN, MonitoringAPs, MonitoringDevices

from aruba_client.schema import (
    AccessPoint,
    AccessPointDetail,
    CentralResponse,
    Device,
    InventoryDevice,
    Port,
    Radio,
    Wlan,
)

logger = structlog.get_logger(__name__)


def _items(response: Any) -> list[dict]:
    if isinstance(response, dict):
        return response.get("items", [])
    return response or []


def _combine_filters(*filters: str | None) -> str | None:
    """Join non-empty filter expressions with ``and`` (Aruba filter syntax)."""
    parts = [f for f in filters if f]
    return " and ".join(parts) if parts else None


def get_access_points(
    conn: NewCentralBase,
    *,
    site_id: str | None = None,
    filter_str: str | None = None,
    sort: str | None = None,
) -> CentralResponse[list[dict], list[AccessPoint]]:
    """List monitored APs (``network-monitoring/v1/aps``) — see ``AccessPoint``."""
    combined = _combine_filters(filter_str, f"siteId eq {site_id}" if site_id else None)
    rows = MonitoringAPs.get_all_aps(conn, filter_str=combined, sort=sort)
    return CentralResponse(rows, AccessPoint.list_from_raw)


def get_access_point_detail(conn: NewCentralBase, serial: str) -> CentralResponse[dict, AccessPointDetail]:
    """Per-AP detail (``network-monitoring/v1/aps/{serial}``) — see ``AccessPointDetail``."""
    return CentralResponse(MonitoringAPs.get_ap_details(conn, serial), AccessPointDetail.from_raw)


def get_access_point_radios(conn: NewCentralBase, serial: str) -> CentralResponse[list[dict], list[Radio]]:
    """Radios of one AP (``network-monitoring/v1/aps/{serial}/radios``) — see ``Radio``."""
    return CentralResponse(_items(MonitoringAPs.get_ap_radios(conn, serial)), Radio.list_from_raw)


def get_access_point_ports(conn: NewCentralBase, serial: str) -> CentralResponse[list[dict], list[Port]]:
    """Wired ports of one AP (``network-monitoring/v1/aps/{serial}/ports``) — see ``Port``."""
    return CentralResponse(_items(MonitoringAPs.get_ap_ports(conn, serial)), Port.list_from_raw)


def get_access_point_wlans(conn: NewCentralBase, serial: str) -> CentralResponse[list[dict], list[Wlan]]:
    """WLANs served by one AP (``network-monitoring/v1/aps/{serial}/wlans``) — see ``Wlan``."""
    return CentralResponse(_items(MonitoringAPs.get_ap_wlans(conn, serial)), Wlan.list_from_raw)


def get_radios(
    conn: NewCentralBase,
    *,
    site_id: str | None = None,
    filter_str: str | None = None,
    sort: str | None = None,
) -> CentralResponse[list[dict], list[Radio]]:
    """List radios fleet-wide (``network-monitoring/v1/radios``) — see ``Radio``.

    Distinct from ``get_access_point_radios``, which returns the radios of one AP.
    """
    combined = _combine_filters(filter_str, f"siteId eq {site_id}" if site_id else None)
    rows = MonitoringAPs.get_all_radios(conn, filter_str=combined, sort=sort)
    return CentralResponse(rows, Radio.list_from_raw)


def get_wlans(
    conn: NewCentralBase,
    *,
    site_id: str | None = None,
    serial: str | None = None,
    filter_str: str | None = None,
    sort: str | None = None,
) -> CentralResponse[list[dict], list[Wlan]]:
    """List WLANs fleet-wide (``network-monitoring/v1/wlans``) — see ``Wlan``.

    Distinct from ``get_access_point_wlans``, which returns the WLANs of one AP.
    """
    rows = WLAN.get_all_wlans(conn, site_id=site_id, serial_number=serial, filter_str=filter_str, sort=sort)
    return CentralResponse(rows, Wlan.list_from_raw)


def get_devices(
    conn: NewCentralBase,
    *,
    filter_str: str | None = None,
    sort: str | None = None,
) -> CentralResponse[list[dict], list[Device]]:
    """List onboarded, monitored devices (``network-monitoring/v1/devices``) — see ``Device``."""
    rows = MonitoringDevices.get_all_devices(conn, filter_str=filter_str, sort=sort)
    return CentralResponse(rows, Device.list_from_raw)


def get_device_inventory(
    conn: NewCentralBase,
    *,
    site_assigned: str | None = None,
    filter_str: str | None = None,
    sort: str | None = None,
) -> CentralResponse[list[dict], list[InventoryDevice]]:
    """Full device inventory incl. not-yet-onboarded (``device-inventory``) — see ``InventoryDevice``."""
    rows = MonitoringDevices.get_all_device_inventory(
        conn, filter_str=filter_str, sort=sort, site_assigned=site_assigned
    )
    return CentralResponse(rows, InventoryDevice.list_from_raw)
