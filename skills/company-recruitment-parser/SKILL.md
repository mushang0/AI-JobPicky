---
name: company-recruitment-parser
description: Investigate and adapt public company recruitment and campus-career sites. Use when a parser task involves a company careers, campus recruitment, jobs, join-us, HCM, ATS, SPA, or public recruitment API page, especially when the site is a known company or may reuse a platform in the company catalog.
---

# Company Recruitment Parser

Use a platform-first, evidence-first workflow. Reuse an existing adapter when the host matches a catalog entry; add company configuration before adding company-specific code.

## Workflow

1. Read the current classifier, parser registry, public job contract, quality gate, and the relevant references below.
2. Match the source URL and spreadsheet company label with `company_profiles.py`. Treat aliases such as subsidiaries and business groups as one company group while preserving the original company label.
3. Identify the platform from the host, page shell, script bundle names, embedded state, and public request paths. Prefer an existing platform family from [platform-catalog.md](references/platform-catalog.md).
4. Inspect one public list page and one public detail page. Use deterministic HTTP first; use the browser only to inspect rendered navigation or Network requests when the shell hides the route. For a catalogued platform, compare against its verified route before exploring a new one.
5. Prefer data sources in this order: public JSON list API, server-rendered JSON, embedded application state, static HTML links, browser-only DOM. Stop at login, CAPTCHA, access control, or a private/unstable mechanism.
6. Reproduce only public requests. Do not store cookies, bearer tokens, temporary query tokens, personal data, or copied production responses. Preserve only endpoint path templates, field names, pagination behavior, and sanitized fixtures.
7. Map every job to the existing collected-job shape. Require a real title, stable source ID when available, public description, and official detail URL. Never use a page title such as “职位详情” as a job title.
8. Make pagination explicit. If the response reports a total, prove that the collected count reaches it; otherwise mark the collection incomplete instead of claiming success.
9. Add the smallest platform-level adapter or company profile needed. Do not create a new parser for a company whose API shape is already covered by an adapter.
10. Add one sanitized fixture for the successful path and one test for the important unsupported/error boundary. Run a small replay before a full corpus replay. For a direct position URL, prove that the adapter does not silently expand it into the whole company list.
11. Classify failures separately as transport, access-control, empty-data, schema, or parser failures. Report reachable-source success separately from raw-link success.

## Repository locations

- Runtime company catalog: `src/jobpicky/collection/company_profiles.py`
- Parser registry: `src/jobpicky/collection/pipeline.py`
- Public parser fallback: `src/jobpicky/collection/parsers/public_web.py`
- Company and platform reference: [company-catalog.md](references/company-catalog.md) and [platform-catalog.md](references/platform-catalog.md)
- Replay output: `artifacts/collection-review/<parser>-YYYYMMDD-HHMMSS/`

## Quality gate

Accept a source only when the result contains real job records and passes the existing quality checks. At minimum verify:

- titles are specific and not generic portal titles;
- descriptions are sourced from the page or public API;
- detail URLs resolve to the official recruitment host or an explicitly configured official host;
- IDs are stable enough for deduplication;
- list pagination is complete or explicitly marked incomplete;
- no model-generated text is used as a job fact;
- incomplete collection does not close historical jobs.

From the repository root, use `uv run python scripts/verify_parser_pipeline.py --input <CSV> --output <DIR> --platform COMPANY_RECRUITMENT_SITE --limit 3` for a smoke replay, then inspect `summary.json` before opening individual cases. Use the full replay only after the smoke result is understood.
