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

"""Read-only wrappers around the Aruba Central ``network-monitoring/v1/clients`` API.

Each function delegates to pycentral's ``Clients`` class (cursor pagination, 429
retry inside ``NewCentralBase.command()``) and returns a
:class:`~aruba_client.schema.CentralResponse`: call ``.parsed()`` for the
typed :class:`~aruba_client.schema.Client` model or ``.raw`` for the
untouched payload.

Get a ``conn`` from :func:`aruba_client.client.get_central_client`.
"""

import structlog
from pycentral import NewCentralBase
from pycentral.new_monitoring import Clients

from aruba_client.schema import CentralResponse, Client

logger = structlog.get_logger(__name__)


def get_clients(
    conn: NewCentralBase,
    *,
    site_id: str | None = None,
    serial: str | None = None,
    filter_str: str | None = None,
    sort: str | None = None,
) -> CentralResponse[list[dict], list[Client]]:
    """List clients (wired + wireless) (``network-monitoring/v1/clients``) — see ``Client``."""
    rows = Clients.get_all_clients(conn, site_id=site_id, serial_number=serial, filter_str=filter_str, sort=sort)
    return CentralResponse(rows, Client.list_from_raw)


def get_wireless_clients(
    conn: NewCentralBase,
    *,
    site_id: str | None = None,
    serial: str | None = None,
    sort: str | None = None,
) -> CentralResponse[list[dict], list[Client]]:
    """List wireless clients only (``clientConnectionType eq 'Wireless'``) — see ``Client``."""
    rows = Clients.get_wireless_clients(conn, site_id=site_id, serial_number=serial, sort=sort)
    return CentralResponse(rows, Client.list_from_raw)


def get_clients_for_device(conn: NewCentralBase, serial: str) -> CentralResponse[list[dict], list[Client]]:
    """List clients associated with one device by serial number — see ``Client``."""
    rows = Clients.get_clients_associated_device(conn, serial)
    return CentralResponse(rows, Client.list_from_raw)


def get_client_detail(conn: NewCentralBase, mac: str) -> CentralResponse[dict, Client]:
    """Detail for one client by MAC (``network-monitoring/v1/clients/{mac}``) — see ``Client``."""
    return CentralResponse(Clients.get_client_details(conn, mac), Client.from_raw)
