# Getting Started

## 1. Create a business profile

Copy:

```text
configs/example-business/business-profile.json
```

Give the copy a lowercase business ID. Keep credentials and private data out of the file.

## 2. Choose or copy a task template

The first safe template is:

```text
templates/competitor-research/task.json
```

Replace example domains, keywords, limits, and output requirements. Start with `research-only` or `test` mode.

## 3. Validate locally

From the repository root:

```bash
python scripts/validate_configs.py \
  --business configs/example-business/business-profile.json \
  --task templates/competitor-research/task.json
```

The validator checks required fields, domain syntax, limits, approval policy, policy compatibility, repository-relative paths, and secret-like field names.

## 4. Submit a workflow request

Use GitHub Issues and select **Universal Browser Agent Request**. Describe the business outcome, approved domains, inputs, outputs, scale, login requirements, consequential actions, runtime, and proof of success.

## 5. Run the prompt-engineering lifecycle

Use:

```text
prompts/system/universal-browser-agent-prompt-engineer.md
```

The assistant should research, interview, assess feasibility, compare options, present a blueprint, and wait for `CONFIRM` before creating the final execution prompt.

## 6. Review through a pull request

Store approved prompts, templates, schemas, and adapters in a feature branch. GitHub Actions checks example configuration, JSON syntax, required safety sections, and likely committed secrets.

## 7. Runtime status

The current release does not execute browsers. The recommended next milestone is a read-only Playwright adapter that:

- accepts a validated task;
- enforces the domain allowlist;
- visits public pages only;
- extracts configured fields;
- records source URLs and timestamps;
- saves screenshots on failure;
- exports JSON, CSV, and Markdown;
- performs no login or state-changing action.

## Recommended first pilot

Use one public-domain competitor research workflow with no login, ten or fewer items, one safe sample run, and manual review of every output.
