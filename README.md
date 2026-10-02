# Oracle EBS Warehouse Location Agents (Azure AI Foundry)

Two Azure AI Foundry prompt agents that recommend warehouse locations from live Oracle E-Business Suite data
running on Oracle Exadata Database Service @ Azure.

| Agent | Role |
|---|---|
| `Hackathon-Oracle-Geo-Postal-code-generator` | Maintains the reference data: geocodes customer/organisation postal codes into `XXWLA_GEO_POSTAL_CACHE` (web search, US Census Gazetteer, Azure Maps or manual) and builds the candidate site list in `XXWLA_CANDIDATE_SITE`. |
| `Hackathon-Oracle-Warehouse-Recommendation-Agent` | Ranks candidate sites against demand (`XXWLA_DEMAND_V`) with a deterministic scoring script, adds cited market research, checks site coordinates with Azure Maps and produces a downloadable report. |

## Architecture

```
Foundry agent ──mcp──────▶ MCP-relay-app (Azure Function, public, VNet-integrated)
   │                          └──▶ mcp-server-vm (private VNet): nginx ─▶ mcp-proxy ─▶ Oracle SQLcl `sql -mcp`
   │                                                                                     └──▶ Exadata @ Azure (EBS, schema MCP_VIEWS, read-only user)
   ├─openapi (managed identity)──▶ Azure Maps Geocoding API (keyless, Entra ID)
   ├─code_interpreter──▶ attached scripts (scoring.py, build_report.py, gaz_load.py)
   └─web_search
```

## Repository layout

| Path | Contents |
|---|---|
| `agents/<agent>/agent.json` | Agent definition template (model, tools, metadata). `$file` entries point to sibling files; `${NAME}` placeholders are filled from `.env`. |
| `agents/<agent>/instructions.md` | System instructions. |
| `agents/<agent>/files/` | Files attached to Code Interpreter. |
| `tools/openapi/azure_maps.json` | OpenAPI 3 spec for Azure Maps forward (`/geocode`) and reverse (`/reverseGeocode`) geocoding. |
| `tools/ebs-vision-mcp-shim/` | Azure Function that relays MCP over SSE from Foundry to the private MCP backend. |
| `tools/ebs-vision-mcp-backend/` | MCP backend config: systemd unit, startup primer, nginx front, `setup.sh` for a fresh Ubuntu 24.04 VM. |
| `db/mcp_views_xxwla.sql` | DDL for the `XXWLA_*` tables and views the agents read and write. `db/export_ddl.sql` regenerates it. |
| `infra/setup.sh` | Keyless Azure Maps account and role assignment. |
| `scripts/` | `export_agent.py`, `deploy_agent.py`, `check_secrets.sh`. |

## Setup

Prerequisites: Azure CLI logged in (`az login`), Python 3.10+, an Azure AI Foundry project, and an Oracle EBS database reachable from a private VNet.

1. `cp .env.example .env` and fill in the values.
2. **Database:** run `db/mcp_views_xxwla.sql` as the `MCP_VIEWS` owner. It ends with the grants `MCP_READER` needs: `SELECT` on the views, plus write access to the two tables the Geo agent maintains.
3. **MCP backend:** on an Ubuntu 24.04 VM in the private VNet, run `sudo tools/ebs-vision-mcp-backend/setup.sh` and follow its manual steps (DB wallet and saved SQLcl connection `EBSDB_MCP`; credentials are never stored in this repo).
4. **MCP shim:** deploy `tools/ebs-vision-mcp-shim/` to a Python 3.12 Function App (Flex Consumption) with VNet integration into the same VNet, and set the app setting `MCP_BACKEND_URL=http://<vm-private-ip>/sse`. In the Foundry project, add a custom MCP connection named `ebs-vision-mcp` pointing to `https://<function-app>.azurewebsites.net/sse`.
5. **Azure Maps:** `FOUNDRY_ACCOUNT=<foundry-account> MAPS_ACCOUNT=<maps-account> ./infra/setup.sh`, then put the printed client ID in `.env` as `AZURE_MAPS_CLIENT_ID`.
6. **Agents:** check what would be created, then deploy:
   ```
   python scripts/deploy_agent.py geo-postal-code --dry-run
   python scripts/deploy_agent.py geo-postal-code
   python scripts/deploy_agent.py warehouse-recommendation
   ```
   Each deploy uploads the Code Interpreter files and creates a new agent version; earlier versions stay available for rollback.

## Updating the repo from Foundry

Agents are edited in the Foundry portal, so the repo is refreshed by exporting:

```
python scripts/export_agent.py            # all agents, latest versions
python scripts/deploy_agent.py warehouse-recommendation --dry-run   # expect: IDENTICAL to live vN
./scripts/check_secrets.sh                # must print "secret scan: clean" before committing
```

`agent.json` records `exported_from_version` so every commit names the Foundry version it came from.

## Security notes

- No keys anywhere. Azure Maps is called with Entra ID: the OpenAPI tool uses `managed_identity` auth (audience `https://atlas.microsoft.com/`), and the token comes from the **Foundry account's** system-assigned identity, which holds `Azure Maps Data Reader`. `x-ms-client-id` (the Maps account ID) is a public identifier, not a secret.
- The MCP shim's `/sse` and `/messages/` routes are anonymous because Foundry's MCP client drops function keys; the security boundary is VNet isolation of the backend and the `MCP_READER` database user, which is limited to `MCP_VIEWS` and read-only except for the two agent-maintained `XXWLA_*` tables.
- The backend's authenticated nginx listeners (`:8080`, `:8443`) use a bearer token generated on the VM by `setup.sh` (`/mcp/config/bearer.secret`); the repo holds only the `${MCP_BACKEND_BEARER_TOKEN}` placeholder.
- The nginx config in this repo omits a debug access-log format used during development on the live VM.
- `.env` is gitignored; `scripts/check_secrets.sh` fails if any `.env` value or secret-like string appears in tracked files.

## Data

`agents/geo-postal-code/files/2025_Gaz_zcta_national Clean txt.txt` is derived from the US Census Bureau 2025 Gazetteer ZCTA file (public domain).
