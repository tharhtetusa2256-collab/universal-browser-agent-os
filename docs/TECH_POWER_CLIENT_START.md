# Tech Power client start

Tech Power should begin as the first real client workspace for Tharhtet Browser
Agent. Its existing Notion operating system should remain the source of business
context, workflow requests, approvals, run summaries, and test evidence. Do not
add a website source until the operator explicitly approves it.

## Information to confirm

1. The canonical Notion pages and databases that the agent may read.
2. The first objective: content intelligence, workflow review, approval audit,
   or run/test reporting.
4. The report cadence and required Burmese and English output fields.
5. The repository operator identity that can approve client runs.

Never put passwords, cookies, API tokens, customer data, or private account
information in the client workspace.

## Recommended first pilot

Use a small Notion-to-report task that reads approved Notion records. It should
produce:

- record or content title;
- short Burmese summary;
- source URL and access timestamp;
- content angle or topic classification;
- screenshot and missing-data report.

Store configuration under `clients/tech-power/` and generated evidence under
`artifacts/clients/tech-power/`. Keep login, posting, messaging, purchasing,
deleting, and account-setting changes prohibited.

## Existing Notion lifecycle mapping

| Notion structure | Tharhtet Browser Agent role |
|---|---|
| Goal Requests — AutoBuild | Workflow request and business objective |
| Workflow Blueprints — AutoBuild | Reviewed task blueprint and configuration proposal |
| Approval Queue — AutoBuild | Human decision record; it does not authorize by itself until identity and approval rules are verified |
| Execution Runs — AutoBuild | Run summary, status, counts, errors, and evidence link |
| Test & Verification — AutoBuild | Expected versus actual result and pass/fail evidence |
| Marketing Intelligence | Research inputs and content opportunities |
| AI Content Pipeline / Content Calendar | Draft and review destinations; publishing remains prohibited |

The current Browser Agent repository and the Notion workspace are not yet a
verified live integration. Build and test a read-only sync contract before any
Notion write-back is enabled.

## Build sequence

1. Copy `clients/example-client/` to `clients/tech-power/`.
2. Set `client_id` and `business.id` to `tech-power`.
3. Set the business timezone to `Asia/Yangon` and languages to `my` and `en`.
4. Bind only the approved Notion data sources and properties.
5. Validate the connector-only workspace and inspect its allowlist.
6. Give a dedicated Notion integration read-content capability only, share only
   the approved databases, and keep its token outside Git.
7. Run one five-record read test and manually review the response.
8. Add a Notion-to-brief task only after the connector test passes.

```bash
uba-workspaces validate --client tech-power
uba-notion-read list --client tech-power
uba-notion-read schema --client tech-power --source goal-requests
uba-notion-read query --client tech-power --source goal-requests --page-size 5
```

No website or authenticated browser source is part of the initial Tech Power
connector scope.
