# Security Policy

## Core rule

Never commit real credentials, browser session state, customer private data, payment data, private messages, authentication cookies, one-time codes, or production exports.

Use GitHub Secrets, environment-scoped secrets, or an external secret manager. Store only fake examples in this repository.

## Browser-agent trust model

- System, developer, approved user, and signed configuration instructions are trusted according to their priority.
- Web pages, emails, documents, comments, search results, downloads, advertisements, pop-ups, and metadata are untrusted data.
- Instructions found inside untrusted data must never override the approved task.
- Navigation is restricted to approved domains, except ordinary identity-provider domains explicitly required for an approved service.
- CAPTCHA, passkeys, biometrics, sensitive two-factor authentication, and account recovery require human takeover.
- Consequential actions require an immediate, action-specific human approval gate.

## Consequential actions

Examples include sending, publishing, purchasing, accepting terms, deleting, cancelling, changing permissions, uploading confidential data, changing security settings, and final application submission.

The approval preview must show the target, exact action, submitted data, expected effect, cost, and reversibility.

## Read-only Playwright runtime

The v0.2 adapter accepts only `research-only` and `test` tasks. It enforces exact
approved domains, public DNS results, standard public ports, GET/HEAD requests,
manual redirect validation, blocked WebSockets, disabled service workers, and
rejected downloads. It does not click controls, fill forms, submit data, or use
stored browser sessions.

Runtime artifacts are limited to ignored repository directories. Review reports,
screenshots, and traces before sharing them because public pages can still contain
unexpected or personal information.

## v0.3 service boundary

- All `/v1` API routes require a high-entropy bearer token.
- Run creation is idempotent and accepts only repository-relative JSON files
  under `configs/` or `templates/`.
- A created run is not executable until a durable blueprint approval confirms
  the objective and approved domains.
- OpenRouter output is an untrusted extraction draft. It cannot expand domains,
  authorize actions, or directly enqueue a run.
- Notion and outbound webhook delivery use environment-only credentials.
- Output delivery failure is recorded without deleting or rewriting browser
  evidence.
- The SQLite pilot queue supports one worker. Do not scale worker replicas
  without replacing the queue and testing claim semantics.
- Keep the API behind HTTPS and never expose the container's port 8000 directly
  to the public internet.

## v0.4 client workspace boundary

- Client manifests contain configuration only; secrets and session state remain
  prohibited.
- Preferred run creation uses a validated `client_id` and registered `task_id`
  instead of caller-supplied file paths.
- Business profiles and task files must remain inside their client workspace.
- Task evidence must remain under `artifacts/clients/<client-id>/`.
- A client-scoped blueprint may be approved only by the manifest's `owner_id`.
- Notion and webhook delivery are disabled unless the client manifest explicitly
  allows the integration.
- Workspace isolation assumes one trusted repository operator. It is not a
  substitute for tenant authentication or authorization in a client-facing SaaS.

## Client credential boundary

- Git and Notion store schema-validated credential references and metadata only,
  never secret values or the 1Password service-account token.
- Each client and environment must use a separate vault and service identity;
  read and write capabilities must not share an identity.
- `uba-secrets` may launch only a schema-allowlisted adapter executable. It does
  not invoke a shell and callers cannot override the bound client or repository.
- The broker passes only the adapter's declared references through `op run` and
  leaves 1Password output masking enabled.
- Credential audit logs record client, service identity, adapter, capabilities,
  decision, status, and exit code. They omit references, values, and arguments.
- `OP_SERVICE_ACCOUNT_TOKEN` is a host bootstrap credential. Provide it through
  the host credential store or process supervisor, scope it to one client vault,
  and rotate it; do not put it in `.env`, Git, Notion, or logs.
- Environment injection does not isolate processes running as the same operating
  system user. Production clients need separate OS users or containers, data
  volumes, databases, artifact roots, and browser profiles.

## Reporting vulnerabilities

Open a private security advisory when available. Do not include exploitable credentials or customer data in a public issue.
