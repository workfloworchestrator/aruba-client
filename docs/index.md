# Aruba Client

Python client for the [Aruba Central](https://developer.arubanetworks.com/aruba-central) network monitoring API. Supports MSP token exchange so a single set of credentials can access all tenant workspaces.

## Authentication

The client uses **MSP (Managed Service Provider) token exchange** (RFC 8693) so that a single set of MSP credentials can access all tenant workspaces — no per-tenant API keys needed.

The authentication flow:

1. Obtain an MSP access token via `client_credentials` grant against the HPE GreenLake OAuth2 endpoint.
2. Resolve the target customer name to a GreenLake workspace ID by querying `/workspaces/v1/msp-tenants`.
3. Exchange the MSP token for a tenant-scoped access token via RFC 8693 token exchange.
4. Use the tenant token with `pycentral.NewCentralBase` to call the Aruba Central API.

Both the MSP token and the workspace name-to-ID mapping are cached in memory (55 min and 1 hour TTL respectively).

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

## The `CentralResponse` parser — type-safe vs raw

Almost every getter returns a `CentralResponse[Raw, Parsed]` — a thin wrapper that
keeps **both** the untouched API payload and a lazily-validated typed model, so you
choose per call site how much you trust the schema:

```python
resp = get_new_central_aps(conn, site=site.id)

aps   = resp.parsed()   # list[AccessPoint] — validated, typed, the normal path
rows  = resp.raw        # list[dict]        — the untouched API payload, always available
```

- **`.parsed()`** runs the model's `from_raw` mapper, **memoizes** the result (the
  parser runs at most once), and returns the typed model. If the payload no longer
  matches the model — a field changed type, a required key vanished — it **raises**.
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

The health endpoint (`get_new_central_sites`) has **no postal address** — the address /
city / zipcode live on the separate config API. Join them with `enrich_addresses`:

```python
registry = get_new_central_sites(conn).parsed()
registry.enrich_addresses(get_new_central_site_configs(conn).raw)   # fills Site.address/.city
```

## Detailed device info

```python
from aruba_client import devices, clients, switches, gateways

# devices.py — APs and per-AP / fleet-wide detail
aps = devices.get_access_points(conn, site_id=site.id).parsed()
detail = devices.get_access_point_detail(conn, aps[0].serial).parsed()
radios = devices.get_radios(conn, site_id=site.id).parsed()
wlans = devices.get_wlans(conn, site_id=site.id).parsed()
inventory = devices.get_device_inventory(conn, site_assigned="UNASSIGNED").parsed()

# clients.py — wired + wireless clients
wifi = clients.get_wireless_clients(conn, site_id=site.id).parsed()

# switches.py / gateways.py — typed list, detail, interfaces, VLANs, ports
sw = switches.get_switches(conn).parsed()
ifaces = switches.get_switch_interfaces(conn, "SW-SERIAL").parsed()
ports = gateways.get_gateway_ports(conn, "GW-SERIAL").parsed()
```

## Schema Models

Response shapes are documented by the pydantic models in `aruba_client.schema`.
Models: `DeviceHealth`, `Site`/`SiteRegistry`, `SiteConfig`, `AccessPoint`,
`AccessPointDetail`, `Radio`, `Port`, `Wlan`, `Device`, `InventoryDevice`,
`Client`, `Switch`, `SwitchDetail`, `SwitchInterface`, `SwitchVlan`, `Gateway`,
`GatewayPort`.

All models subclass `_ArubaModel` which uses `extra="ignore"` — unknown API fields
are dropped, not rejected, so an API that adds fields never breaks parsing.
