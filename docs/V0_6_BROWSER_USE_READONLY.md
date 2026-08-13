# v0.6 Browser Use public read-only adapter

v0.6 adds an **optional, experimental Browser Use adapter** for low-risk public
research. It does not replace the existing Playwright runtime and it is not
wired into automatic task routing yet.

## Purpose

Use this adapter when the site is public and dynamic enough that agentic
navigation is useful, but the task must remain non-authenticated and
non-consequential.

Use the existing Playwright runtime when deterministic execution, strict
GET/HEAD-only request enforcement, selector-based extraction, or the existing
production evidence contract is more important than agentic navigation.

## Install

The core package keeps Browser Use optional:

```bash
python -m pip install ".[browser-use]"
```

The optional extra is pinned to the current 0.13 minor line so upstream breaking
changes do not silently enter the runtime.

## Configuration

The pilot reuses the existing OpenRouter credential and adds only a model
setting:

```text
OPENROUTER_API_KEY=...
UBA_BROWSER_USE_MODEL=openai/gpt-4.1-mini
```

Do not commit the API key. The key remains environment-provided and is not
written into Browser Use evidence reports.

## Run an approved task

```bash
uba-browser-use \
  --business configs/example-business/business-profile.json \
  --task templates/competitor-research/task.json \
  --max-steps 20
```

The task must already pass the repository's normal business/task validation.
The adapter accepts only `research-only` and `test` task modes.

## Read-only action contract

For Browser Use 0.13.7, only these actions may be exposed by this adapter:

- `navigate`
- `go_back`
- `wait`
- `scroll`
- `find_text`
- `search_page`
- `find_elements`
- `extract`
- `screenshot`
- `switch`
- `dropdown_options`
- `done`

`find_text` is Browser Use's built-in scroll-to-text operation. `search_page`
and `find_elements` are accepted only as Browser Use's fixed read-only DOM
inspection tools. Arbitrary JavaScript execution remains excluded.

The following current upstream defaults are explicitly excluded:

- search-engine search
- click/input/send-keys
- file upload
- arbitrary JavaScript evaluation
- dropdown selection
- PDF/file creation, including `save_as_pdf`
- local file read/write/replace
- tab close

The exclusion list is not the primary safety boundary. After Browser Use builds
its tool registry, the adapter reads the registry's concrete `actions` mapping
and compares every registered action name to the allowlist. Any new or
unexpected upstream action causes startup to fail closed.

After a run, the adapter also checks every recorded action name against the same
allowlist. A prohibited action in history makes the run fail instead of being
reported as successful.

## Domain and network controls

The adapter applies defense in depth:

1. every configured start URL passes the repository `DomainPolicy` before launch;
2. Browser Use receives only the task's approved domains;
3. Browser Profile blocks literal IP-address navigation;
4. every observed top-level URL is checked again with `DomainPolicy`, including
   public DNS resolution checks;
5. visited URLs from run history are validated again before success is reported.

This is intentionally **not identical** to the Playwright runtime's request-level
network enforcement. Browser Use can load normal webpage subresources and page
scripts. Therefore v0.6 does not claim the stricter Playwright invariant that
all browser network requests are GET/HEAD-only. Tasks requiring that invariant
must continue using `uba-run` / `ReadOnlyPlaywrightRuntime`.

## Authentication and challenges

v0.6 does not provide:

- login or persistent sessions;
- cookies, passwords, tokens, OTPs, or other sensitive data to the agent;
- CAPTCHA solving or bypass;
- passkey or 2FA handling;
- stealth or anti-bot bypass;
- form submission, messaging, publishing, purchasing, deletion, or account
  changes.

If a public research path requires one of those capabilities, the agent is
instructed to stop and report that human takeover or a later approved runtime is
required.

## Evidence

Each run writes a dedicated directory under the validated task destination:

```text
<task-destination>/browser-use/<run-id>/
├── report.json
├── report.md
└── screenshot-*.png   # when Browser Use history contains screenshots
```

The report contains:

- task/run identifiers;
- model name;
- approved domains and start URLs;
- final result;
- visited URLs;
- action names;
- extracted content;
- errors;
- screenshot paths;
- explicit safety metadata including `execution_authorized=false`.

Raw model thoughts / chain-of-thought are intentionally not persisted.

## CI compatibility gate

`.github/workflows/browser-use-compat.yml` installs the optional Browser Use
extra and verifies, without launching a browser or calling a model API, that:

- the pinned Browser Use dependency still installs on Python 3.12;
- the adapter unit tests pass;
- the current upstream tool registry contains no unexpected action after the
  exclusion list is applied;
- required read-only actions still exist;
- the expected Browser Use OpenRouter provider module remains importable;
- `BrowserProfile` still supports the approved-domain and IP-blocking settings.

Normal repository CI still runs without Browser Use installed. This keeps the
core runtime lightweight and prevents every CI run from adding Browser Use or
LLM cost.

## v0.6 boundary

v0.6 is deliberately manual and opt-in. It does **not** add Browser Use to the
FastAPI worker route and it does not change how approved runs are executed.

The next milestone, v0.6.1, should add a deterministic tool router that can
choose between Playwright and Browser Use only after policy and evaluation
criteria are defined. Until then, production/default execution remains
Playwright.
