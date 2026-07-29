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

## Reporting vulnerabilities

Open a private security advisory when available. Do not include exploitable credentials or customer data in a public issue.
