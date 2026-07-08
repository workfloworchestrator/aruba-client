# aruba-client

Python client for the [Aruba Central](https://developer.arubanetworks.com/aruba-central) network monitoring API.

Uses **MSP token exchange** (RFC 8693) so a single set of MSP credentials can access all tenant workspaces — no per-tenant API keys needed. Returns typed pydantic models with a `CentralResponse` wrapper that keeps both the raw payload and a lazily-parsed model.

[![Tests](https://github.com/workfloworchestrator/aruba-client/actions/workflows/tests.yml/badge.svg)](https://github.com/workfloworchestrator/aruba-client/actions/workflows/tests.yml)
[![Docs](https://readthedocs.org/projects/aruba-client/badge/?version=latest)](https://aruba-client.readthedocs.io/en/latest/)

## Installation

```bash
pip install aruba-client
```

## Quick start

```bash
export ARUBA_MSP_CLIENT_ID=...
export ARUBA_MSP_CLIENT_SECRET=...
export ARUBA_MSP_WORKSPACE_ID=...
export ARUBA_GREENLAKE_OAUTH_URL=https://sso.common.cloud.hpe.com/as/token.oauth2
```

```python
from aruba_client import get_central_client, get_new_central_sites, get_new_central_aps

conn = get_central_client("My Tenant")
registry = get_new_central_sites(conn).parsed()
site = registry.find_by_name("My Site")
aps = get_new_central_aps(conn, site=site.id).parsed()
```

See the [documentation](https://aruba-client.readthedocs.io) for full API reference.
