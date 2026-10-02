# Demo prompts

Prompts used to record the demo, as provided by the development team. Run them in the Foundry agent playground, each in a new conversation.

## Geo Agent (`Hackathon-Oracle-Geo-Postal-code-generator`) - status

Status only. Operating unit: Vision Operations. Period: 01-FEB-2002 to 01-OCT-2010. Run the status query and show the exact SQL and the raw result. Report: total units, geocoded units %, pending postal codes, and warehouses missing coordinates. Do not write, update or delete anything.

## Geo Agent - candidate sites

Read only. Operating unit: Vision Operations. List all active candidate sites and existing warehouse nodes in XXWLA_CANDIDATE_SITE for this operating unit: site_id, site_name, region, city, state, latitude, longitude, is_existing_node. Show the exact SQL and the raw result. Do not write, update or delete anything.

## Recommendation Agent (`Hackathon-Oracle-Warehouse-Recommendation-Agent`) - smoke test

Smoke test. Operating unit: Vision Operations. Period: 01-FEB-2002 to 01-OCT-2010. Region: ALL. Run Steps 1 and 2 only. For each step, show the exact SQL and the raw result. List /mnt/data and report the row count for each file written. Confirm the demand file row count equals postal_codes from Step 1a. Do not run scoring, research or the report. End with a PASS/FAIL table.

## Recommendation Agent - full recommendation

Recommend a location for a new warehouse. Operating unit: Vision Operations. Period: 01-FEB-2002 to 01-OCT-2010. Region: ALL. Use default metric, service hours and weights, and state which defaults you applied. Show the preflight control totals (postal codes, total units) from Oracle. Use Azure Maps to confirm the coordinates of the shortlisted sites, and web search for market research with sources. Build the Excel workbook with build_report.py and give me the download link. In the summary include: recommended site and reason, whether it differs from rank 1 and why, geocoded %, and PROVISIONAL if below 80%.
