# Submission materials

| File | What it is |
|---|---|
| `SUBMISSION.md` | Text for each field of the hackathon submission form. Search for `TODO` before submitting. |
| `Strategic_Warehouse_Location_Planner.docx` / `.pdf` | Full solution document: problem, setup, architecture, test evidence, Microsoft IQ, design decisions, readiness, demo script. |
| `architecture.png` | Solution architecture diagram (numbers match the flow in the document). |
| `demo-prompts.md` | Prompts used to record the demo. |
| `evidence/` | Test evidence: the workbook from the 02 Oct 2026 end-to-end run. Add screenshots of the Foundry run trace here. |

`_source/` holds the raw developer uploads and is not published (gitignored).

- Videos are not stored in git. Host the demo video (e.g. YouTube unlisted) and put the link in `SUBMISSION.md`.
- Run `./scripts/check_secrets.sh` before committing. It scans text files but cannot read inside PDFs, Office files or images, so check those by hand for keys, connection strings, tenant/subscription IDs and customer data.
