# Client secret management

Tharhtet Browser Agent keeps personal and client credentials outside Git,
Notion, task files, and generated artifacts. The repository stores only
validated policy metadata and 1Password secret references.

## Current foundation

The Tech Power development workspace declares:

- service identity metadata: `sa-tech-power-dev-read`;
- allowed vault metadata: `Client-Tech-Power-Dev`;
- capability: `notion.read`;
- approved adapter: `uba-notion-read`.

These names and references are configuration examples. This repository does not
create a vault, service account, item, token, or live integration.

Inspect the non-secret policy:

```bash
uba-secrets list --client tech-power
```

After separately creating and authorizing the real 1Password resources, an
operator can launch the allowlisted reader through the broker:

```bash
uba-secrets run --client tech-power --adapter notion-read -- \
  query --source goal-requests --page-size 5
```

The broker writes a temporary mode-`0600` reference file, invokes `op run`
without disabling output masking, passes only a small environment allowlist,
removes the temporary file, and appends redacted events to
`service-data/clients/<client-id>/credential-audit.jsonl`.

## External setup checklist

Do not complete these steps until the operator explicitly approves external
credential changes:

1. Create a separate development vault for Tech Power.
2. Create a read-only Notion integration and place its token in that vault.
3. Create a service account that can read only the Tech Power development vault.
4. Provide `OP_SERVICE_ACCOUNT_TOKEN` from the host credential store or process
   supervisor, never from this repository's `.env` file.
5. Run a read-only smoke query against one approved Notion data source.
6. Review the redacted audit record and rotate the bootstrap token if exposed.

Create different identities and vaults for personal work, every client,
development versus production, and read versus write capabilities. Before any
authenticated production adapter, also isolate the OS user or container,
database, volume, artifact directory, and browser profile.
