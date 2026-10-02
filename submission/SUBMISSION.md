# Open Hack Submission — form text

Form: https://github.com/Azure/odaa-ai-partnerHackathon/issues/new?template=submission.yml
Issue title: `[Submission]: Strategic Warehouse Location Planner — Powered by AI`. **Due 02 October 2026, 11:59 PM PST.**

Each `###` section is one field of the form, in the form's order. Paste the text under it into that field.
The full write-up is `submission/Strategic_Warehouse_Location_Planner.pdf`.

---

### Team Name

Accenture

### Team Members

Simo Vilmunen (@svilmune), Mayuresh Kolhatkar, Marc Gero, Vikrant Deshmukh

### Project Title

Strategic Warehouse Location Planner — Powered by AI

### GitHub Repository Link

https://github.com/svilmune/strategic-warehouse-location-planner

### Video Demo Link

https://youtu.be/9FL4lKdYcIM

### Business Problem & Target Users

Warehouse location is a capital decision, but it's usually made with partial information. The demand history sits in Oracle E-Business Suite, while market conditions such as rent, labour, transport links and risk are spread across broker reports and websites. EBS stores addresses, not map coordinates. It has no record of warehouses that don't exist yet. Pulling data, geocoding, researching markets and scoring in spreadsheets takes weeks, rarely gets redone when assumptions change, and gives a capital committee conclusions without the working.

**What it does:** two Microsoft Foundry agents turn Oracle EBS shipment history into a ranked, repeatable shortlist of US warehouse locations. Each shortlisted site gets market research with sources, and the output is an Excel workbook that states its own limitations.

**Target users:**
- **Supply chain and network planners** (main users) ask for a recommendation, test service levels, regions or weightings, and re-run when needed.
- **Capital committee and finance reviewers** review the workbook, where the scoring, the research and the limitations are shown separately.
- **Supply chain and operations leaders** decide which sites go on to due diligence.
- **Oracle EBS administrators** control read-only access and the two reference tables the agents may update.

**Measurable impact:**
- **Measured:** in the test run on Vision Operations (2002–2010), 51 postal codes and 4.8M shipped units were read from Oracle. 99.9% of units were geocoded, 100 candidate sites were ranked, and 3 shortlisted sites got 12 research findings: 11 cited, and 1 marked ABSENT where no valid source existed. The result is a committee-ready workbook from one conversation.
- **Expected, not yet measured against a baseline:** first answer in a working session instead of a multi-week spreadsheet exercise, and repeatable rankings. For scale, the team's manual research put the annual occupancy-cost gap between candidate US markets at about $412,500 for a 100,000 sq ft building.
- Not yet measured against a baseline: the agent has not yet supported a live business decision.

### Architecture & Approach

**The approach in one line:** the code does the maths, the AI does the judgement, and Oracle stays the system of record.

**Oracle AI Database@Azure.** Oracle E-Business Suite runs on Oracle Exadata Database Service on Oracle Database@Azure. A custom schema, `MCP_VIEWS`, holds read-only views over standard EBS tables (`XXWLA_DEMAND_V`, `XXWLA_NETWORK_V`, `XXWLA_GEO_PENDING_V`) and two tables the agents maintain (`XXWLA_GEO_POSTAL_CACHE`, `XXWLA_CANDIDATE_SITE`).

**Oracle MCP.** Oracle SQLcl's built-in MCP server is the only path from the agents into Oracle. It runs on a VM in a private Azure VNet as `MCP_READER`, behind `mcp-proxy` and nginx, and Foundry reaches it through a VNet-integrated Azure Function. Oracle grants, not just prompts, decide what the agents can do: SELECT on all five objects, write access on the two agent tables only, and no DELETE on geocodes.

**Microsoft Foundry Agent Service.** Two agents run on Claude Opus 4.8:
- **Geo Agent** prepares the data. It geocodes pending postal codes with Azure Maps, highest volume first, and writes them back to Oracle with a read-back check. It proposes candidate sites around the demand-weighted centre, and reports data readiness.
- **Recommendation Agent** decides and explains.
  - *Tier 1, Compute:* it pulls data through Oracle MCP, and `scoring.py` in Code Interpreter checks control totals and ranks the candidates deterministically.
  - *Tier 2, Research:* it researches the shortlist on the web with citations.
  - *Tier 3, Reason:* it recommends one site and must explain any divergence from rank 1.
  - `build_report.py` builds the Excel workbook and refuses to build it if the research breaks the rules.
- **Azure Maps** supplies coordinates and the location check through a keyless OpenAPI tool that authenticates with the Foundry account's managed identity.

**Flow:**
1. The planner asks the Geo Agent to prepare data.
2. The Geo Agent reads pending postal codes through Oracle MCP.
3. Azure Maps returns coordinates.
4. The Geo Agent writes geocodes and candidates to Oracle.
5. The planner asks the Recommendation Agent for a recommendation.
6. The Recommendation Agent reads demand, network, geocodes and candidates, read-only.
7. `scoring.py` ranks the candidates.
8. Azure Maps checks the shortlist's coordinates, and web research covers each shortlisted site with citations.
9. `build_report.py` validates the research and builds the workbook.
10. The planner reviews the workbook and decides.

**Microsoft IQ.** We'd rather be straight about which IQ components this build uses than draw them all into a diagram:
- **Web IQ:** we intended it for Tier 2 market research in place of the generic web search tool. We configured it as an OpenAPI tool with the Foundry account's managed identity. Web IQ accepted the token but rejected the identity ("Application … is not authorized to access this service"), because Web IQ access requires tenant enrollment in the Microsoft Frontier Preview Program, and our tenant isn't enrolled. So we kept Foundry web search. The tool definition is ready in the repo (`tools/webiq/`).
- **Fabric IQ:** not used in this build. Our companion Order-to-Ship Recovery Agent uses Fabric with mirrored EBS data. Here the next step is to mirror the demand view into Fabric for larger volumes.
- **Foundry IQ:** not used in this build. Next step: a knowledge base of approved market reports alongside web research.
- **Work IQ:** not used in this build. Next step: planner context from email and Teams, such as sites the business has already ruled out.

Why we didn't force them in: this agent needs a few hundred aggregated rows per question, and every number must trace to an Oracle query. A direct SQL path through Oracle MCP met that with the fewest parts.

### Setup & Run Instructions

The repository README has full setup and run instructions; the solution document covers the same steps with smoke tests. In summary:
1. Copy `.env.example` to `.env` and fill in the subscription, Foundry project endpoint and Azure Maps client ID. No secrets go in the repo.
2. Create the five `XXWLA_*` objects and the MCP user's grants with `db/mcp_views_xxwla.sql`.
3. Build the Oracle MCP backend (SQLcl MCP server) on an Ubuntu VM in the private VNet with `tools/ebs-vision-mcp-backend/setup.sh`. Deploy the relay Function in `tools/ebs-vision-mcp-shim/` and add the `ebs-vision-mcp` connection in Foundry.
4. Create the keyless Azure Maps account and its role assignment with `infra/setup.sh`.
5. Deploy the agents with `python scripts/deploy_agent.py geo-postal-code` and `python scripts/deploy_agent.py warehouse-recommendation`. Use `--dry-run` to preview.
6. Run the smoke tests, then the run sequence: Geo status, Geo Mode E until at least 80% of units are geocoded, Geo Mode B for candidates, then the recommendation. Prompts are in `submission/demo-prompts.md`.

### Production & Microsoft Marketplace Readiness

**Current maturity:** working prototype, run end to end on Oracle's Vision demo data on Oracle Database@Azure.

**Implemented safeguards and validation results:**
- **Database access:** least-privilege Oracle grants, verified. Agents are limited to approved SQL, one statement per call, and the database blocks deletion of geocodes.
- **Network:** the MCP backend sits in a private VNet with no public IP, and the database is never exposed.
- **No keys:** Azure Maps uses managed identity, and the repository is secret-scanned before every commit.
- **Deterministic scoring:** a script computes the ranking, not the model, so the same inputs give the same ranking. Control totals from Oracle are checked before scoring. Computed and researched results are kept separate, and missing evidence is marked ABSENT rather than counted against a site.
- **Report validation:** the report builder refuses invalid research, and every report lists its limitations. Results below 80% geocoded are marked PROVISIONAL.
- **Validation:** an end-to-end run on 02 Oct 2026 gave a FINAL ranking (99.9% geocoded, no overrides). It recommended Columbus OH at rank 1, and the Azure Maps location check matched 3 of 3 sites. The results were checked by hand against the Oracle control totals. The workbook is in `submission/evidence/`.
- **Release and rollback:** agents are versioned in Foundry. Definitions, scripts, DDL and MCP configuration are kept as code, with export, dry-run diff and deploy scripts.

**Production gaps and next steps:**
- **Shared database user:** both agents use one MCP user. Next step: a separate read-only user for the Recommendation Agent.
- **Anonymous relay:** the MCP relay endpoints are anonymous because Foundry's MCP client drops function keys. Next step: Entra-authenticated MCP or Foundry network injection.
- **No automated evaluation:** next steps are a golden-set evaluation, prompt-injection testing on web content, and a data-handling review for web search queries.
- **Single MCP VM, not load tested:** move Tier 1 scoring into Oracle or Fabric for larger volumes.
- **Basic monitoring:** Foundry traces and Application Insights on the relay only; no dashboards or alerts.
- **No CI/CD pipeline.**
- **Simplified distances:** great-circle distance times a road factor, not routed drive time. Next step: Azure Maps routing.

**Microsoft Marketplace plans and intended offer type:** a Marketplace offer isn't part of this submission. Not planned at this stage; no offer type has been chosen.

**Marketplace readiness gaps and next steps:**
- A one-step installer (Bicep or azd) for the schema objects, grants and agents.
- Guided customer onboarding, with a file-upload mode for customers without DBA support.
- Country and ERP parameters.
- A defined support model.
- Partner Center registration, offer listing, security and privacy documentation, and certification are not started.

### Bonus (Optional)

- **AI write-back into Oracle with database-enforced limits:** the Geo Agent enriches EBS with sourced coordinates and candidate sites. Oracle grants, not just prompts, decide what it can change.
- **Trust-but-verify pipeline:** control totals from SQL, an integrity check in the scorer, and a report builder that refuses bad research. The model is never the last line of defence.
- **Proposed new Oracle–Microsoft connection:** a private Oracle MCP on Oracle Database@Azure, reached from Foundry through a VNet-integrated relay. Keyless Azure Maps from Foundry agents via managed identity. The Oracle geocode cache becomes a shared reference asset for other agents.
- **Web IQ:** prepared for cited research, and blocked only by access.

### Submission Checklist

- [ ] My repository contains a completed solution, clear setup/run instructions, and a description of architecture and approach.
- [ ] My demo video shows the application running, the core user flow, and evidence that Oracle data is being retrieved and used by the AI.
- [ ] I verified my video link works by opening it in a private/incognito browser window.
