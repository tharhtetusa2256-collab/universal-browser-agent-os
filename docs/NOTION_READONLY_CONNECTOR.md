# Notion read-only connector

The connector reads explicitly allowlisted Notion data sources for one client.
It does not expose page creation, updates, comments, deletes, schema changes, or
generic HTTP requests.

## Security boundary

- Use a dedicated Notion internal integration with read-content capability only.
- Store its token only in `UBA_NOTION_READ_TOKEN`.
- Never commit tokens, cookies, exported customer data, or webhook URLs.
- Every data-source ID and returned property must be declared in the client's
  `notion-readonly.json` file.
- The query operation uses Notion's read-only data-source query endpoint even
  though that endpoint uses HTTP POST.
- Website sources and authenticated browser sessions are outside this connector.

The connector does not make Notion an approval authority. The Browser Agent's
durable owner approval remains authoritative until identity binding between the
systems is separately designed and verified.

## Tech Power

The initial Tech Power allowlist contains:

- Goal Requests — AutoBuild;
- Workflow Blueprints — AutoBuild;
- Approval Queue — AutoBuild;
- Execution Runs — AutoBuild;
- Test & Verification — AutoBuild;
- Marketing Intelligence — Tech Power.

List the configured scope without a token:

```bash
uba-notion-read list --client tech-power
```

After creating a read-content-only Notion integration, sharing only the approved
databases with it, and setting the token in the environment, test one schema and
one small query:

```bash
uba-notion-read schema --client tech-power --source goal-requests
uba-notion-read query --client tech-power --source goal-requests --page-size 5
```

These commands print API responses to standard output. Redirect only into an
approved local artifact path when retention is required.
