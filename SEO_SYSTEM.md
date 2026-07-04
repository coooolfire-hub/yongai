# YongAI SEO System

This is the automated SEO maintenance system for the static YongAI site.

## What Runs Automatically

- Scans all HTML pages.
- Checks title, meta description, canonical URL, H1, robots, and local links.
- Rebuilds `sitemap.xml` from indexable pages.
- Rebuilds `robots.txt` with the sitemap location.
- Generates `docs/seo-report.md`.
- Generates `docs/seo-content-calendar.md` from `seo/topics.json`.
- Generates editable article briefs in `docs/seo-briefs/`.
- Generates `docs/affiliate-report.md` from `seo/affiliate-links.json`.
- Rebuilds `_redirects`; filled affiliate links become `/go/tool-id` redirect routes.
- Runs daily in GitHub Actions and commits report/sitemap updates.

## Local Commands

```bash
python3 scripts/seo_system.py
python3 scripts/seo_system.py --write
```

Use this before deploying:

```bash
python3 scripts/seo_system.py --write --fail-on-issues
```

## Content Strategy

The system intentionally creates a content calendar and SEO briefs rather than automatically publishing thin AI-generated pages. YongAI should prioritize:

- tool-vs-tool comparisons
- buying decision pages
- China-accessible AI tool guides
- workflow stacks for indie builders and creators
- transparent affiliate and sponsored disclosures

Update `seo/topics.json` when you want the system to plan new topics.

Update `seo/affiliate-links.json` after you receive a partner link. The report will show which high-priority tools still need affiliate links.

When an `affiliate_url` is filled, the system adds a redirect like:

```txt
/go/cursor https://your-affiliate-link.example 302
```

Use those `/go/...` links in pages once you want all outbound clicks to be managed in one place.
