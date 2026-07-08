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

"""Typed models for the Aruba Central ``network-monitoring`` responses.

These models — not prose in the client docstrings — document the response
shapes. Each `from_raw` maps the (camelCase) API keys onto stable snake_case
attributes and keeps the untouched payload in ``raw``; unknown/renamed fields
are ignored rather than rejected, so an API bump never breaks parsing outright.

The client and device wrappers return a :class:`CentralResponse`: call
``.parsed()`` for the validated model (the normal path) or ``.raw`` for the
untouched ``list[dict]``/``dict`` when the API has drifted ahead of a model.
"""

from collections.abc import Callable
from typing import Any, Generic, Self, TypeVar

from pydantic import BaseModel, ConfigDict

RawT = TypeVar("RawT")
ParsedT = TypeVar("ParsedT")


class CentralResponse(Generic[RawT, ParsedT]):
    """An Aruba Central payload kept as both raw data and a lazily-parsed model.

    ``.raw`` is the untouched API response (``list[dict]`` or ``dict``).
    ``.parsed()`` validates it into a typed model and memoizes the result; it
    raises if the payload no longer matches the model — fall back to ``.raw``.
    """

    def __init__(self, raw: RawT, parser: Callable[[RawT], ParsedT]) -> None:
        self.raw = raw
        self._parser = parser
        self._parsed: ParsedT | None = None

    def parsed(self) -> ParsedT:
        if self._parsed is None:
            self._parsed = self._parser(self.raw)
        return self._parsed


def _s(raw: dict, key: str) -> str:
    """Read ``key`` from ``raw`` as a string, mapping a missing/None value to ""."""
    value = raw.get(key)
    return "" if value is None else str(value)


class _ArubaModel(BaseModel):
    """Base for the parsed models: ignore unknown fields and offer list parsing."""

    model_config = ConfigDict(extra="ignore")

    @classmethod
    def from_raw(cls, raw: dict) -> Self:  # pragma: no cover - overridden
        raise NotImplementedError

    @classmethod
    def list_from_raw(cls, rows: list[dict]) -> list[Self]:
        return [cls.from_raw(row) for row in rows]


class DeviceHealth(BaseModel):
    good: int = 0
    fair: int = 0
    poor: int = 0

    @property
    def total(self) -> int:
        return self.good + self.fair + self.poor


class Site(BaseModel):
    id: str
    name: str
    address: str | None = None
    city: str | None = None
    device_types: dict[str, DeviceHealth] = {}

    @classmethod
    def from_raw(cls, raw: dict) -> "Site":
        device_types = {
            dt["name"]: DeviceHealth(**{g["name"].lower(): g["value"] for g in dt["health"]["groups"]})
            for dt in raw.get("deviceTypes", [])
        }
        # network-monitoring/v1 renamed the site label to ``siteName``; v1alpha1 used ``name``.
        name = raw.get("siteName") or raw.get("name", "")
        return cls(id=raw["id"], name=name, device_types=device_types)

    def get_health(self, device_type: str = "Access Points") -> DeviceHealth:
        # A config-only site (present in Aruba's config API but not yet reporting
        # device health) has no entry here; treat that as zero rather than KeyError.
        return self.device_types.get(device_type, DeviceHealth())


class SiteRegistry(BaseModel):
    sites: list[Site] = []

    @classmethod
    def from_raw(cls, data: list[dict]) -> "SiteRegistry":
        return cls(sites=[Site.from_raw(s) for s in data])

    def enrich_addresses(self, config_sites: list[dict]) -> None:
        """Merge the config-sites response (which carries address/city) into the registry by id.

        Sites already known from the monitoring/health endpoint get their
        ``address``/``city`` filled in. Config-only sites — present in Aruba's
        config API but not (yet) reporting device health — are appended as
        health-less entries so DIY address matching and the "available sites"
        error listing both see the complete set. The config payload has no site
        *name*, so we fall back to its ``collectionName``/``scopeName`` label.
        """
        by_id = {str(s["id"]): s for s in config_sites if s.get("id") is not None}
        known_ids = {site.id for site in self.sites}
        self.sites = [
            (
                site.model_copy(update={"address": config.get("address"), "city": config.get("city")})
                if (config := by_id.get(site.id))
                else site
            )
            for site in self.sites
        ]
        self.sites.extend(
            Site(
                id=site_id,
                name=config.get("collectionName") or config.get("scopeName") or "",
                address=config.get("address"),
                city=config.get("city"),
            )
            for site_id, config in by_id.items()
            if site_id not in known_ids
        )

    def resolve_name(self, site_id: str) -> str | None:
        site = self.resolve(site_id)
        return site.name if site else None

    def resolve(self, site_id: str) -> Site | None:
        return next((s for s in self.sites if s.id == site_id), None)

    def find_by_name(self, name: str) -> Site | None:
        return next((s for s in self.sites if s.name == name), None)


class AccessPoint(_ArubaModel):
    """One access point from the ``network-monitoring/v1/aps`` list."""

    serial: str = ""
    name: str = ""
    model: str = ""
    mac: str = ""
    status: str = ""
    site_id: str = ""
    site_name: str = ""
    part_number: str = ""
    firmware: str = ""
    uptime_millis: int | None = None
    last_seen_at: str = ""
    client_count: int | None = None
    wlan_count: int | None = None
    ipv4: str = ""
    public_ipv4: str = ""
    role: str = ""
    deployment: str = ""
    raw: dict[str, Any] = {}

    @classmethod
    def from_raw(cls, raw: dict) -> "AccessPoint":
        return cls(
            serial=_s(raw, "serialNumber"),
            name=_s(raw, "deviceName"),
            model=_s(raw, "model"),
            mac=_s(raw, "macAddress"),
            status=_s(raw, "status"),
            site_id=_s(raw, "siteId"),
            site_name=_s(raw, "siteName"),
            part_number=_s(raw, "partNumber"),
            firmware=_s(raw, "firmwareVersion"),
            uptime_millis=raw.get("uptimeInMillis"),
            last_seen_at=_s(raw, "lastSeenAt"),
            client_count=raw.get("clientCount"),
            wlan_count=raw.get("wlanCount"),
            ipv4=_s(raw, "ipv4"),
            public_ipv4=_s(raw, "publicIpv4"),
            role=_s(raw, "role"),
            deployment=_s(raw, "deployment"),
            raw=raw,
        )


class AccessPointDetail(_ArubaModel):
    """Per-AP detail from ``network-monitoring/v1/aps/{serial}``.

    Identity/hardware/uplink fields are promoted to attributes; the nested
    ``radios``/``ports``/``wlans`` lists stay raw, and ``raw`` keeps the full
    response (``apStats``, ``bandSelection``, ``modem``, ...).
    """

    serial: str = ""
    name: str = ""
    model: str = ""
    mac: str = ""
    manufacturer: str = ""
    status: str = ""
    site_id: str = ""
    firmware: str = ""
    country_code: str = ""
    mode: str = ""
    role: str = ""
    mesh_role: str = ""
    deployment: str = ""
    ipv4: str = ""
    ipv6: str = ""
    public_ipv4: str = ""
    subnet_mask: str = ""
    default_gateway: str = ""
    current_uplink_in_use: str = ""
    negotiated_power: str = ""
    last_seen_at: str = ""
    last_reboot_reason: str = ""
    uptime_millis: int | None = None
    notes: str = ""
    radios: list[dict] = []
    ports: list[dict] = []
    wlans: list[dict] = []
    raw: dict[str, Any] = {}

    @classmethod
    def from_raw(cls, raw: dict) -> "AccessPointDetail":
        return cls(
            serial=_s(raw, "serialNumber"),
            name=_s(raw, "deviceName"),
            model=_s(raw, "model"),
            mac=_s(raw, "macAddress"),
            manufacturer=_s(raw, "manufacturer"),
            status=_s(raw, "status"),
            site_id=_s(raw, "siteId"),
            firmware=_s(raw, "firmwareVersion"),
            country_code=_s(raw, "countryCode"),
            mode=_s(raw, "mode"),
            role=_s(raw, "role"),
            mesh_role=_s(raw, "meshRole"),
            deployment=_s(raw, "deployment"),
            ipv4=_s(raw, "ipv4"),
            ipv6=_s(raw, "ipv6"),
            public_ipv4=_s(raw, "publicIpv4"),
            subnet_mask=_s(raw, "subnetMask"),
            default_gateway=_s(raw, "defaultGateway"),
            current_uplink_in_use=_s(raw, "currentUplinkInUse"),
            negotiated_power=_s(raw, "negotiatedPower"),
            last_seen_at=_s(raw, "lastSeenAt"),
            last_reboot_reason=_s(raw, "lastRebootReason"),
            uptime_millis=raw.get("uptimeInMillis"),
            notes=_s(raw, "notes"),
            radios=raw.get("radios") or [],
            ports=raw.get("ports") or [],
            wlans=raw.get("wlans") or [],
            raw=raw,
        )


class Radio(_ArubaModel):
    """One radio from ``network-monitoring/v1/aps/{serial}/radios``."""

    radio_number: int | None = None
    band: str = ""
    band_range: str = ""
    bandwidth: str = ""
    channel: str = ""
    channel_utilization: str = ""
    client_count: int | None = None
    mac: str = ""
    mode: str = ""
    noise_floor: str = ""
    power: str = ""
    status: str = ""
    site_id: str = ""
    raw: dict[str, Any] = {}

    @classmethod
    def from_raw(cls, raw: dict) -> "Radio":
        return cls(
            radio_number=raw.get("radioNumber"),
            band=_s(raw, "band"),
            band_range=_s(raw, "bandRange"),
            bandwidth=_s(raw, "bandwidth"),
            channel=_s(raw, "channel"),
            channel_utilization=_s(raw, "channelUtilization"),
            client_count=raw.get("clientCount"),
            mac=_s(raw, "macAddress"),
            mode=_s(raw, "mode"),
            noise_floor=_s(raw, "noiseFloor"),
            power=_s(raw, "power"),
            status=_s(raw, "status"),
            site_id=_s(raw, "siteId"),
            raw=raw,
        )


class Port(_ArubaModel):
    """One wired port from ``network-monitoring/v1/aps/{serial}/ports``."""

    name: str = ""
    port_index: int | None = None
    status: str = ""
    speed: str = ""
    duplex: str = ""
    connector: str = ""
    mac: str = ""
    access_vlan: str = ""
    native_vlan: str = ""
    allowed_vlan: str = ""
    vlan_mode: str = ""
    raw: dict[str, Any] = {}

    @classmethod
    def from_raw(cls, raw: dict) -> "Port":
        return cls(
            name=_s(raw, "name"),
            port_index=raw.get("portIndex"),
            status=_s(raw, "status"),
            speed=_s(raw, "speed"),
            duplex=_s(raw, "duplex"),
            connector=_s(raw, "connector"),
            mac=_s(raw, "macAddress"),
            access_vlan=_s(raw, "accessVlan"),
            native_vlan=_s(raw, "nativeVlan"),
            allowed_vlan=_s(raw, "allowedVlan"),
            vlan_mode=_s(raw, "vlanMode"),
            raw=raw,
        )


class Wlan(_ArubaModel):
    """One WLAN, from a per-AP (``aps/{serial}/wlans``) or fleet-wide (``wlans``) list.

    The fleet-wide list adds ``id``/``type``; both fields stay empty for the
    per-AP shape that omits them.
    """

    id: str = ""
    wlan_name: str = ""
    type: str = ""
    band: str = ""
    security: str = ""
    security_level: str = ""
    status: str = ""
    vlan: str = ""
    raw: dict[str, Any] = {}

    @classmethod
    def from_raw(cls, raw: dict) -> "Wlan":
        return cls(
            id=_s(raw, "id"),
            wlan_name=_s(raw, "wlanName"),
            type=_s(raw, "type"),
            band=_s(raw, "band"),
            security=_s(raw, "security"),
            security_level=_s(raw, "securityLevel"),
            status=_s(raw, "status"),
            vlan=_s(raw, "vlan"),
            raw=raw,
        )


class Device(_ArubaModel):
    """One device from ``network-monitoring/v1/devices`` (APs, switches, gateways)."""

    serial: str = ""
    name: str = ""
    device_type: str = ""
    model: str = ""
    mac: str = ""
    status: str = ""
    config_status: str = ""
    site_id: str = ""
    site_name: str = ""
    firmware: str = ""
    uptime_millis: int | None = None
    last_seen_at: str = ""
    part_number: str = ""
    role: str = ""
    deployment: str = ""
    raw: dict[str, Any] = {}

    @classmethod
    def from_raw(cls, raw: dict) -> "Device":
        return cls(
            serial=_s(raw, "serialNumber"),
            name=_s(raw, "deviceName"),
            device_type=_s(raw, "deviceType"),
            model=_s(raw, "model"),
            mac=_s(raw, "macAddress"),
            status=_s(raw, "status"),
            config_status=_s(raw, "configStatus"),
            site_id=_s(raw, "siteId"),
            site_name=_s(raw, "siteName"),
            firmware=_s(raw, "firmwareVersion"),
            uptime_millis=raw.get("uptimeInMillis"),
            last_seen_at=_s(raw, "lastSeenAt"),
            part_number=_s(raw, "partNumber"),
            role=_s(raw, "role"),
            deployment=_s(raw, "deployment"),
            raw=raw,
        )


class InventoryDevice(_ArubaModel):
    """One device from ``network-monitoring/v1/device-inventory`` (incl. not-yet-onboarded)."""

    serial: str = ""
    name: str = ""
    device_type: str = ""
    model: str = ""
    mac: str = ""
    status: str = ""
    is_provisioned: bool | None = None
    subscription_key: str = ""
    tier: str = ""
    stack_id: str = ""
    scope_id: str = ""
    site_id: str = ""
    site_name: str = ""
    firmware: str = ""
    part_number: str = ""
    role: str = ""
    raw: dict[str, Any] = {}

    @classmethod
    def from_raw(cls, raw: dict) -> "InventoryDevice":
        return cls(
            serial=_s(raw, "serialNumber"),
            name=_s(raw, "deviceName"),
            device_type=_s(raw, "deviceType"),
            model=_s(raw, "model"),
            mac=_s(raw, "macAddress"),
            status=_s(raw, "status"),
            is_provisioned=raw.get("isProvisioned"),
            subscription_key=_s(raw, "subscriptionKey"),
            tier=_s(raw, "tier"),
            stack_id=_s(raw, "stackId"),
            scope_id=_s(raw, "scopeId"),
            site_id=_s(raw, "siteId"),
            site_name=_s(raw, "siteName"),
            firmware=_s(raw, "firmwareVersion"),
            part_number=_s(raw, "partNumber"),
            role=_s(raw, "role"),
            raw=raw,
        )


class SiteConfig(_ArubaModel):
    """One site from the config API ``network-config/v1alpha1/sites`` (carries the postal address).

    This is the address/geo view of a site (no health), joined to a monitoring
    :class:`Site` by ``id`` via :meth:`SiteRegistry.enrich_addresses`. The config
    payload has no site *name* — only ``collectionName``/``scopeName`` labels.
    """

    id: str = ""
    address: str = ""
    city: str = ""
    zipcode: str = ""
    state: str = ""
    country: str = ""
    timezone: str = ""
    latitude: str = ""
    longitude: str = ""
    type: str = ""
    collection_name: str = ""
    scope_name: str = ""
    device_count: int | None = None

    @classmethod
    def from_raw(cls, raw: dict) -> "SiteConfig":
        return cls(
            id=_s(raw, "id"),
            address=_s(raw, "address"),
            city=_s(raw, "city"),
            zipcode=_s(raw, "zipcode"),
            state=_s(raw, "state"),
            country=_s(raw, "country"),
            timezone=_s(raw, "timezone"),
            latitude=_s(raw, "latitude"),
            longitude=_s(raw, "longitude"),
            type=_s(raw, "type"),
            collection_name=_s(raw, "collectionName"),
            scope_name=_s(raw, "scopeName"),
            device_count=raw.get("deviceCount"),
        )


class Client(_ArubaModel):
    """One client from ``network-monitoring/v1/clients`` (wired or wireless)."""

    id: str = ""
    name: str = ""
    host_name: str = ""
    mac: str = ""
    ipv4: str = ""
    ipv6: str = ""
    connection_type: str = ""
    status: str = ""
    site_id: str = ""
    site_name: str = ""
    username: str = ""
    os: str = ""
    manufacturer: str = ""
    vendor: str = ""
    category: str = ""
    role: str = ""
    snr: int | None = None
    connected_device_serial: str = ""
    connected_device_type: str = ""
    connected_to: str = ""
    wireless_band: str = ""
    wireless_channel: str = ""
    wireless_security: str = ""
    wlan_name: str = ""
    bssid: str = ""
    phy_type: str = ""
    authentication_type: str = ""
    vlan_id: str = ""
    vlan_name: str = ""
    last_seen_at: str = ""
    connected_at: str = ""
    raw: dict[str, Any] = {}

    @classmethod
    def from_raw(cls, raw: dict) -> "Client":
        return cls(
            id=_s(raw, "id"),
            name=_s(raw, "clientName"),
            host_name=_s(raw, "hostName"),
            mac=_s(raw, "macAddress"),
            ipv4=_s(raw, "ipv4"),
            ipv6=_s(raw, "ipv6"),
            connection_type=_s(raw, "clientConnectionType"),
            status=_s(raw, "status"),
            site_id=_s(raw, "siteId"),
            site_name=_s(raw, "siteName"),
            username=_s(raw, "userName"),
            os=_s(raw, "clientOperatingSystem"),
            manufacturer=_s(raw, "clientManufacturer"),
            vendor=_s(raw, "clientVendor"),
            category=_s(raw, "clientCategory"),
            role=_s(raw, "role"),
            snr=raw.get("snr"),
            connected_device_serial=_s(raw, "connectedDeviceSerial"),
            connected_device_type=_s(raw, "connectedDeviceType"),
            connected_to=_s(raw, "connectedTo"),
            wireless_band=_s(raw, "wirelessBand"),
            wireless_channel=_s(raw, "wirelessChannel"),
            wireless_security=_s(raw, "wirelessSecurity"),
            wlan_name=_s(raw, "wlanName"),
            bssid=_s(raw, "bssid"),
            phy_type=_s(raw, "phyType"),
            authentication_type=_s(raw, "authenticationType"),
            vlan_id=_s(raw, "vlanId"),
            vlan_name=_s(raw, "vlanName"),
            last_seen_at=_s(raw, "lastSeenAt"),
            connected_at=_s(raw, "connectedAt"),
            raw=raw,
        )


class Switch(_ArubaModel):
    """One switch from the ``network-monitoring/v1/switches`` list.

    The per-switch detail (:class:`SwitchDetail`), interfaces
    (:class:`SwitchInterface`) and VLANs (:class:`SwitchVlan`) are fetched
    separately by the ``switches`` wrappers. The nested ``switchTrends`` perf
    series is left in ``raw`` only.
    """

    serial: str = ""
    name: str = ""
    model: str = ""
    mac: str = ""
    status: str = ""
    site_id: str = ""
    site_name: str = ""
    firmware: str = ""
    uptime_millis: int | None = None
    last_seen_at: str = ""
    ipv4: str = ""
    ipv6: str = ""
    public_ip: str = ""
    j_number: str = ""
    stack_id: str = ""
    stack_member_id: str = ""
    switch_type: str = ""
    role: str = ""
    deployment: str = ""
    raw: dict[str, Any] = {}

    @classmethod
    def from_raw(cls, raw: dict) -> "Switch":
        return cls(
            serial=_s(raw, "serialNumber"),
            name=_s(raw, "deviceName"),
            model=_s(raw, "model"),
            mac=_s(raw, "macAddress"),
            status=_s(raw, "status"),
            site_id=_s(raw, "siteId"),
            site_name=_s(raw, "siteName"),
            firmware=_s(raw, "firmwareVersion"),
            uptime_millis=raw.get("uptimeInMillis"),
            last_seen_at=_s(raw, "lastSeenAt"),
            ipv4=_s(raw, "ipv4"),
            ipv6=_s(raw, "ipv6"),
            public_ip=_s(raw, "publicIp"),
            j_number=_s(raw, "jNumber"),
            stack_id=_s(raw, "stackId"),
            stack_member_id=_s(raw, "stackMemberId"),
            switch_type=_s(raw, "switchType"),
            # Switches expose their role as ``switchRole`` (there is no ``role`` key).
            role=_s(raw, "switchRole"),
            deployment=_s(raw, "deployment"),
            raw=raw,
        )


class SwitchDetail(_ArubaModel):
    """Per-switch detail from ``network-monitoring/v1/switches/{serial}``.

    Same identity/hardware fields as the list :class:`Switch`, plus the
    detail-only health/config fields. Resolves only for an online switch; an
    offline stack member returns 404. ``switchTrends`` stays in ``raw``.
    """

    serial: str = ""
    name: str = ""
    model: str = ""
    mac: str = ""
    manufacturer: str = ""
    status: str = ""
    config_status: str = ""
    site_id: str = ""
    site_name: str = ""
    firmware: str = ""
    uptime_millis: int | None = None
    last_seen_at: str = ""
    last_config_change: int | None = None
    last_restart_reason: str = ""
    ipv4: str = ""
    ipv6: str = ""
    public_ip: str = ""
    j_number: str = ""
    stack_id: str = ""
    switch_type: str = ""
    switch_link_type: str = ""
    role: str = ""
    deployment: str = ""
    health: str = ""
    health_reasons: dict[str, Any] = {}
    raw: dict[str, Any] = {}

    @classmethod
    def from_raw(cls, raw: dict) -> "SwitchDetail":
        return cls(
            serial=_s(raw, "serialNumber"),
            name=_s(raw, "deviceName"),
            model=_s(raw, "model"),
            mac=_s(raw, "macAddress"),
            manufacturer=_s(raw, "manufacturer"),
            status=_s(raw, "status"),
            config_status=_s(raw, "configStatus"),
            site_id=_s(raw, "siteId"),
            site_name=_s(raw, "siteName"),
            firmware=_s(raw, "firmwareVersion"),
            uptime_millis=raw.get("uptimeInMillis"),
            last_seen_at=_s(raw, "lastSeenAt"),
            last_config_change=raw.get("lastConfigChange"),
            last_restart_reason=_s(raw, "lastRestartReason"),
            ipv4=_s(raw, "ipv4"),
            ipv6=_s(raw, "ipv6"),
            public_ip=_s(raw, "publicIp"),
            j_number=_s(raw, "jNumber"),
            stack_id=_s(raw, "stackId"),
            switch_type=_s(raw, "switchType"),
            switch_link_type=_s(raw, "switchLinkType"),
            role=_s(raw, "switchRole"),
            deployment=_s(raw, "deployment"),
            health=_s(raw, "health"),
            health_reasons=raw.get("healthReasons") or {},
            raw=raw,
        )


class SwitchInterface(_ArubaModel):
    """One interface from ``network-monitoring/v1/switches/{serial}/interfaces``."""

    id: str = ""
    name: str = ""
    index: int | None = None
    port_index: int | None = None
    module: str = ""
    status: str = ""
    admin_status: str = ""
    oper_status: str = ""
    speed: int | None = None
    duplex: str = ""
    mtu: int | None = None
    connector: str = ""
    ipv4: str = ""
    vlan_mode: str = ""
    native_vlan: int | None = None
    allowed_vlans: list[str] = []
    allowed_vlan_ids: list[int] = []
    poe_status: str = ""
    poe_class: str = ""
    uplink: bool | None = None
    lag: str = ""
    description: str = ""
    alias: str = ""
    neighbour: str = ""
    neighbour_port: str = ""
    neighbour_type: str = ""
    neighbour_family: str = ""
    stp_port_role: str = ""
    stp_port_state: str = ""
    stp_instance_id: int | None = None
    stp_instance_type: str = ""
    transceiver_model: str = ""
    transceiver_serial: str = ""
    transceiver_type: str = ""
    transceiver_status: str = ""
    transceiver_state: str = ""
    serial_number: str = ""
    raw: dict[str, Any] = {}

    @classmethod
    def from_raw(cls, raw: dict) -> "SwitchInterface":
        return cls(
            id=_s(raw, "id"),
            name=_s(raw, "name"),
            index=raw.get("index"),
            port_index=raw.get("portIndex"),
            module=_s(raw, "module"),
            status=_s(raw, "status"),
            admin_status=_s(raw, "adminStatus"),
            oper_status=_s(raw, "operStatus"),
            speed=raw.get("speed"),
            duplex=_s(raw, "duplex"),
            mtu=raw.get("mtu"),
            connector=_s(raw, "connector"),
            ipv4=_s(raw, "ipv4"),
            vlan_mode=_s(raw, "vlanMode"),
            native_vlan=raw.get("nativeVlan"),
            allowed_vlans=[v for v in (raw.get("allowedVlans") or []) if v],
            allowed_vlan_ids=raw.get("allowedVlanIds") or [],
            poe_status=_s(raw, "poeStatus"),
            poe_class=_s(raw, "poeClass"),
            uplink=raw.get("uplink"),
            lag=_s(raw, "lag"),
            description=_s(raw, "description"),
            alias=_s(raw, "alias"),
            neighbour=_s(raw, "neighbour"),
            neighbour_port=_s(raw, "neighbourPort"),
            neighbour_type=_s(raw, "neighbourType"),
            neighbour_family=_s(raw, "neighbourFamily"),
            stp_port_role=_s(raw, "stpPortRole"),
            stp_port_state=_s(raw, "stpPortState"),
            stp_instance_id=raw.get("stpInstanceId"),
            stp_instance_type=_s(raw, "stpInstanceType"),
            transceiver_model=_s(raw, "transceiverModel"),
            transceiver_serial=_s(raw, "transceiverSerial"),
            transceiver_type=_s(raw, "transceiverType"),
            transceiver_status=_s(raw, "transceiverStatus"),
            transceiver_state=_s(raw, "transceiverState"),
            serial_number=_s(raw, "serialNumber"),
            raw=raw,
        )


class SwitchVlan(_ArubaModel):
    """One VLAN from ``network-monitoring/v1/switches/{serial}/vlans``."""

    id: str = ""
    name: str = ""
    status: str = ""
    type: str = ""
    voice: str = ""
    ipv4: str = ""
    tagged_ports: list[str] = []
    untagged_ports: list[str] = []
    interfaces: list[str] = []
    raw: dict[str, Any] = {}

    @classmethod
    def from_raw(cls, raw: dict) -> "SwitchVlan":
        return cls(
            id=_s(raw, "id"),
            name=_s(raw, "name"),
            status=_s(raw, "status"),
            type=_s(raw, "type"),
            voice=_s(raw, "voice"),
            ipv4=_s(raw, "ipv4"),
            tagged_ports=raw.get("taggedPorts") or [],
            untagged_ports=raw.get("untaggedPorts") or [],
            interfaces=raw.get("interfaces") or [],
            raw=raw,
        )


class Gateway(_ArubaModel):
    """One gateway from ``network-monitoring/v1/gateways`` (list and detail share this shape).

    Per-gateway ports are modelled by :class:`GatewayPort`; uplinks are fetched
    separately and returned raw by the ``gateways`` wrappers (no sample to model
    yet). ``cpu_utilization``/``memory_utilization`` are the flat live metrics
    the gateway list exposes.
    """

    serial: str = ""
    name: str = ""
    model: str = ""
    mac: str = ""
    mac_range: str = ""
    status: str = ""
    site_id: str = ""
    site_name: str = ""
    firmware: str = ""
    uptime_millis: int | None = None
    ipv4: str = ""
    role: str = ""
    mode: str = ""
    cluster_name: str = ""
    device_function: str = ""
    reboot_reason: str = ""
    cpu_utilization: int | None = None
    memory_utilization: int | None = None
    raw: dict[str, Any] = {}

    @classmethod
    def from_raw(cls, raw: dict) -> "Gateway":
        return cls(
            serial=_s(raw, "serialNumber"),
            name=_s(raw, "deviceName"),
            model=_s(raw, "model"),
            mac=_s(raw, "macAddress"),
            mac_range=_s(raw, "macRange"),
            status=_s(raw, "status"),
            site_id=_s(raw, "siteId"),
            site_name=_s(raw, "siteName"),
            firmware=_s(raw, "firmwareVersion"),
            uptime_millis=raw.get("uptimeInMillis"),
            # Gateways expose their IP as ``ipAddress`` (there is no ``ipv4`` key).
            ipv4=_s(raw, "ipAddress"),
            role=_s(raw, "role"),
            mode=_s(raw, "mode"),
            cluster_name=_s(raw, "clusterName"),
            device_function=_s(raw, "deviceFunction"),
            reboot_reason=_s(raw, "rebootReason"),
            cpu_utilization=raw.get("cpuUtilization"),
            memory_utilization=raw.get("memoryUtilization"),
            raw=raw,
        )


class GatewayPort(_ArubaModel):
    """One port from ``network-monitoring/v1/gateways/{serial}/ports``.

    ``mtu``/``speed`` come back as strings (e.g. ``"1500 bytes"``, ``"Auto"``);
    the nested ``usage``/``throughput`` byte counters are kept raw.
    """

    id: str = ""
    name: str = ""
    port_number: str = ""
    port_type: str = ""
    admin_state: str = ""
    oper_state: str = ""
    health: str = ""
    health_reasons: list[Any] = []
    vlan: str = ""
    mtu: str = ""
    speed: str = ""
    duplex: str = ""
    connector_type: str = ""
    mac: str = ""
    total_packets: int | None = None
    broadcast_packets: int | None = None
    multicast_packets: int | None = None
    crc_errors: int | None = None
    collisions: int | None = None
    runts: int | None = None
    giants: int | None = None
    usage: dict[str, Any] = {}
    throughput: dict[str, Any] = {}
    raw: dict[str, Any] = {}

    @classmethod
    def from_raw(cls, raw: dict) -> "GatewayPort":
        return cls(
            id=_s(raw, "id"),
            name=_s(raw, "name"),
            port_number=_s(raw, "portNumber"),
            port_type=_s(raw, "portType"),
            admin_state=_s(raw, "adminState"),
            oper_state=_s(raw, "operState"),
            health=_s(raw, "health"),
            health_reasons=raw.get("healthReasons") or [],
            vlan=_s(raw, "vlan"),
            mtu=_s(raw, "mtu"),
            speed=_s(raw, "speed"),
            duplex=_s(raw, "duplex"),
            connector_type=_s(raw, "connectorType"),
            mac=_s(raw, "macAddress"),
            total_packets=raw.get("totalPackets"),
            broadcast_packets=raw.get("broadcastPackets"),
            multicast_packets=raw.get("multicastPackets"),
            crc_errors=raw.get("crcErrors"),
            collisions=raw.get("collisions"),
            runts=raw.get("runts"),
            giants=raw.get("giants"),
            usage=raw.get("usage") or {},
            throughput=raw.get("throughput") or {},
            raw=raw,
        )
