---
name: parser-maintainer
description: Manually investigate one real parser gap, implement the smallest safe parser change, and verify it.
---

# Parser Maintainer

Use Ponytail throughout. This is a developer-triggered workflow; never schedule it or run it in production.

1. Read `AGENTS.md`, `CLAUDE.md`, the three baseline docs, the classifier, parser registry,
   related parser tests, and `docs/collection/parser-playbook.md`.
2. Generate a small gap report with
   `uv run python scripts/report_parser_gaps.py <sheet> --limit-rows 20`.
   Never dump or read a complete JSON, CSV, spreadsheet, response, or artifact into context.
   Inspect counts, keys, selected fields, bounded rows, or `summary.json` first; use tools such as
   `head`, `sed`, `jq`, or `rg` with explicit limits. Open one minimal case only when the summary
   cannot explain a failure. Never expose secrets or personal data in terminal output.
3. Choose one real gap. Check classification first, then prefer extending an existing parser.
   Add a new platform parser only when the platform is genuinely new.
4. Inspect only public pages. Prefer a stable public API, then embedded JSON, then server HTML.
   Use command-line HTTP and deterministic code first. Browser-control skills are an exploration
   fallback only when those methods cannot reveal a platform's runtime structure; use them to learn
   the minimum DOM/API behavior, never as the production or batch parser. Stop at login, CAPTCHA,
   access control, or unstable private mechanisms.
5. Make the smallest change. Do not change public contracts, add an Agent framework or dependency,
   refactor unrelated code, or claim unsupported pagination/templates are complete.
6. Add one minimal sanitized fixture and focused tests for the successful path and the important
   unsupported/error boundary.
   For a manual review, run `scripts/verify_parser_pipeline.py --platform <PLATFORM>`;
   start with a small `--limit`, use `--limit 0` only when a full rerun is needed, and inspect
   `summary.json` before individual cases. Keep platform-specific diagnostic scripts only when they
   capture evidence the generic runner does not.
7. Update `docs/collection/parser-playbook.md` with verified recognition, data entry, pagination,
   mappings, pitfalls, resolution, fixture/test paths, and remaining limits. Keep it concise and
   correct it whenever later investigation disproves an entry.
8. Run:

   ```bash
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy src tests
   uv run pytest
   ```

9. Review the diff for secrets, raw personal data, oversized responses, and unrelated changes.
   Ask before the local commit. Never push, open a PR, merge, or deploy without explicit approval.
