# Aruba Client

Python client for the [Aruba Central](https://developer.arubanetworks.com/aruba-central) network monitoring API and the [HPE Aruba UXI](https://developer.arubanetworks.com/uxi) sensor API. Supports MSP token exchange so a single set of credentials can access all tenant workspaces.

## Authentication

The client uses **MSP (Managed Service Provider) token exchange** (RFC 8693) so that a single set of MSP credentials can access all tenant workspaces; no per-tenant API keys needed.

The authentication flow:

1. Obtain an MSP access token via `client_credentials` grant against the HPE GreenLake OAuth2 endpoint.
2. Resolve the target customer name to a GreenLake workspace ID by querying `/workspaces/v1/msp-tenants`.
3. Exchange the MSP token for a tenant-scoped access token via RFC 8693 token exchange.
4. Use the tenant token with `pycentral.NewCentralBase` to call the Aruba Central API.

Both the MSP token and the workspace name-to-ID mapping are cached in memory (55 min and 1 hour TTL respectively).

UXI is a separate GreenLake service with its own API client: a plain `client_credentials` token, no MSP exchange. See [UXI sensors](#uxi-user-experience-insight) below.

## Installation

```bash
pip install aruba-client
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ARUBA_MSP_CLIENT_ID` | Yes | API client ID from the MSP workspace |
| `ARUBA_MSP_CLIENT_SECRET` | Yes | API client secret from the MSP workspace |
| `ARUBA_MSP_WORKSPACE_ID` | Yes | MSP workspace ID (hex, no hyphens) |
| `ARUBA_GREENLAKE_OAUTH_URL` | Yes | HPE GreenLake OAuth2 base URL |
| `ARUBA_BASE_URL` | No | Central API base URL (default: `https://de3.api.central.arubanetworks.com`) |

The UXI client reads its own `ARUBA_UXI_*` variables, listed under [UXI sensors](#uxi-user-experience-insight).

## The `CentralResponse` parser: type-safe vs raw

Almost every getter returns a `CentralResponse[Raw, Parsed]`, a thin wrapper that
keeps **both** the untouched API payload and a lazily-validated typed model, so you
choose per call site how much you trust the schema:

```python
resp = get_new_central_aps(conn, site=site.id)

aps   = resp.parsed()   # list[AccessPoint] - validated, typed, the normal path
rows  = resp.raw        # list[dict]        - the untouched API payload, always available
```

- **`.parsed()`** runs the model's `from_raw` mapper, **memoizes** the result (the
  parser runs at most once), and returns the typed model. If the payload no longer
  matches the model (a field changed type, a required key vanished), it **raises**.
- **`.raw`** is the original `list[dict]`/`dict` straight from pycentral. It never
  raises, so it's the escape hatch when the API has drifted ahead of a model.

## Usage

```python
from aruba_client import get_central_client, get_new_central_sites, get_new_central_aps

# Get a tenant-scoped client (reads ARUBA_* env vars by default)
conn = get_central_client("My Tenant Name")

# Fetch all sites with device health
registry = get_new_central_sites(conn).parsed()      # SiteRegistry

# Look up a specific site
site = registry.find_by_name("My Site Name")
health = site.get_health("Access Points")
print(f"Total APs: {health.total}, Good: {health.good}, Fair: {health.fair}, Poor: {health.poor}")

# Fetch APs, filtered by site
aps = get_new_central_aps(conn, site=site.id).parsed()   # list[AccessPoint]
```

### Explicit configuration

```python
from aruba_client import ArubaConfig, get_central_client

config = ArubaConfig(
    MSP_CLIENT_ID="my-client-id",
    MSP_CLIENT_SECRET="my-secret",
    MSP_WORKSPACE_ID="abcdef123456",
    GREENLAKE_OAUTH_URL="https://sso.common.cloud.hpe.com/as/token.oauth2",
)
conn = get_central_client("My Tenant", config=config)
```

### Site addresses

The health endpoint (`get_new_central_sites`) has **no postal address**; the address /
city / zipcode live on the separate config API. Join them with `enrich_addresses`:

```python
registry = get_new_central_sites(conn).parsed()
registry.enrich_addresses(get_new_central_site_configs(conn).raw)   # fills Site.address/.city
```

## Detailed device info

```python
from aruba_client import devices, clients, switches, gateways

# devices.py: APs and per-AP / fleet-wide detail
aps = devices.get_access_points(conn, site_id=site.id).parsed()
detail = devices.get_access_point_detail(conn, aps[0].serial).parsed()
radios = devices.get_radios(conn, site_id=site.id).parsed()
wlans = devices.get_wlans(conn, site_id=site.id).parsed()
inventory = devices.get_device_inventory(conn, site_assigned="UNASSIGNED").parsed()

# clients.py: wired + wireless clients
wifi = clients.get_wireless_clients(conn, site_id=site.id).parsed()

# switches.py / gateways.py: typed list, detail, interfaces, VLANs, ports
sw = switches.get_switches(conn).parsed()
ifaces = switches.get_switch_interfaces(conn, "SW-SERIAL").parsed()
ports = gateways.get_gateway_ports(conn, "GW-SERIAL").parsed()
```

## UXI (User Experience Insight)

[HPE Aruba UXI](https://developer.arubanetworks.com/uxi) sensors are not part of Aruba
Central. Their API is a separate HPE GreenLake service (`https://api.capenetworks.com/networking-uxi/v1alpha1`,
an alpha API) and it is authorised by a GreenLake **API client bound to the "User Experience
Insight" service**, not by the MSP credentials above: the MSP token and the tenant tokens it is
exchanged for are rejected with `403 HPE_GL_ERROR_FORBIDDEN`. Create the API client in the
GreenLake workspace that owns the UXI dashboard (*Manage Workspace > Personal API clients*,
service "User Experience Insight (EU Central)" or "(US West)"); the owning user needs the
UXI Admin or UXI Unrestricted Read Only role.

**One API client per dashboard.** A UXI API client is bound to the UXI *instance* (dashboard) of
the workspace it was created in: its token carries an `application_instance_id` claim and the
UXI API authorises on that claim. The RFC 8693 token exchange that `get_central_client` relies on
changes the *workspace* of a token but not its application instance, so a client created in an
MSP workspace keeps seeing the MSP workspace's own (usually empty) dashboard after the exchange.
An MSP that manages several tenants therefore needs one UXI API client per tenant workspace,
created while switched into that workspace, and one `UxiConfig` per tenant.

Pick the region the dashboard is **provisioned** in (GreenLake *Services > My Services* shows it).
It is independent of the Central region: dashboards migrated from the pre-GreenLake UXI cloud
live in US West even when the access points are in EU Central. The `x-region` header has to
match the dashboard's region or the API answers 403.

### UXI environment variables

| Variable | Required | Description |
|---|---|---|
| `ARUBA_UXI_CLIENT_ID` | Yes | GreenLake API client ID for the UXI service |
| `ARUBA_UXI_CLIENT_SECRET` | Yes | GreenLake API client secret |
| `ARUBA_UXI_REGION` | Yes | `eu-production` or `us-production`: the region the dashboard is provisioned in, sent as the `x-region` header (no default, a wrong region fails silently) |
| `ARUBA_UXI_OAUTH_TOKEN_URL` | No | OAuth2 token endpoint (default: `https://sso.common.cloud.hpe.com/as/token.oauth2`) |
| `ARUBA_UXI_BASE_URL` | No | UXI API root (default: `https://api.capenetworks.com/networking-uxi/v1alpha1`) |

### Sensors of a site

UXI organises sensors in a *group tree*. When each group is named after its Aruba Central
site (the convention this helper is built for), the sensors of a site are found by name:

```python
from aruba_client import get_uxi_client, uxi

client = get_uxi_client()                                       # reads ARUBA_UXI_* env vars

registry = uxi.get_groups(client).parsed()                       # UxiGroupRegistry (the whole tree)
group = uxi.find_group(registry, site.name)                      # UxiGroupNotFoundError if absent
sensors = uxi.get_group_sensors(client, registry.subtree_ids(group)).parsed()   # list[UxiSensor]

statuses = {s.id: uxi.get_sensor_status(client, s.id).parsed() for s in sensors}
online = sum(status.is_online is True for status in statuses.values())
print(f"{group.name}: {online}/{len(sensors)} sensors online")
```

- `find_group` matches the name **exactly** (case-sensitive). A UXI group name is unique only
  among siblings, so a name that occurs more than once in the tree raises `ArubaClientError`
  listing the candidate paths instead of silently picking one.
- `registry.subtree_ids(group)` counts sensors in the group *and* its descendants (a sensor in
  "Example Campus / Building A" belongs to the campus). Pass `{group.id}` for the group alone.
- `get_group_sensors` reads `/sensor-group-assignments` (the authoritative mapping) and the
  sensor list once each; it never issues one request per sensor.
- `UxiSensorStatus.is_online` is `None` for a sensor that has never reported and only turns
  `False` after 90 minutes of silence. A confirmed `ERROR` in `status.issues` is the quicker
  signal that something is wrong. Muted issues are still listed.

The lower-level getters follow the Central ones: `uxi.get_groups`, `uxi.get_sensors`
(optionally `sensor_id=`; there is no `GET /sensors/{id}`), `uxi.get_sensor_group_assignments`
and `uxi.get_sensor_status` all return a `CentralResponse`. Any other list endpoint of the API
(`/agents`, `/service-tests`, `/wired-networks`, ...) is reachable raw through
`client.iter_items("/agents")`, which handles the cursor pagination (`limit` is at most 100).

### Explicit UXI configuration and bring-your-own token

```python
from aruba_client import UxiClient, UxiConfig, get_uxi_client

# One UxiConfig per dashboard, e.g. looked up by tenant name in an MSP setup.
config = UxiConfig(CLIENT_ID="my-client-id", CLIENT_SECRET="my-secret", REGION="us-production")
client = get_uxi_client(config=config)

# Or wrap a bearer token obtained elsewhere; it is never logged or shown in repr().
client = UxiClient(token, region="eu-production")
```

### Rate limit and errors

The UXI API allows 5 requests per second per customer. A `429`, `5xx` or connection error is
retried up to 3 times with exponential backoff (1 s, 2 s); after that, and for any other
non-200 response, an `ArubaClientError` is raised with a one-line message that starts with the
status code and the GreenLake error code, for example
`UXI GET /groups failed (403 HPE_GL_ERROR_FORBIDDEN): The user has insufficient permissions ... [debugId=...]`.
Observed codes: `400 HPE_GL_ERROR_BAD_REQUEST` (`limit` above 100), `400
HPE_GL_NETWORKING_UXI_MALFORMED_CURSOR`, `403 HPE_GL_ERROR_FORBIDDEN` (wrong region or
instance), `404 HPE_GL_ERROR_NOT_FOUND` (unknown sensor), `429 HPE_GL_ERROR_TOO_MANY_REQUESTS`.

## Schema Models

Response shapes are documented by the pydantic models in `aruba_client.schema`.
Models: `DeviceHealth`, `Site`/`SiteRegistry`, `SiteConfig`, `AccessPoint`,
`AccessPointDetail`, `Radio`, `Port`, `Wlan`, `Device`, `InventoryDevice`,
`Client`, `Switch`, `SwitchDetail`, `SwitchInterface`, `SwitchVlan`, `Gateway`,
`GatewayPort`, and for UXI `UxiGroup`/`UxiGroupRegistry`, `UxiSensor`,
`UxiSensorGroupAssignment`, `UxiSensorStatus`, `UxiSensorIssue`.

All models subclass `_ArubaModel` which uses `extra="ignore"`: unknown API fields
are dropped, not rejected, so an API that adds fields never breaks parsing.
