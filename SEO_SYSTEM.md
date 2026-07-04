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
- Generates editable noindex HTML article drafts in `drafts/`.
- Generates semi-automatic social distribution copy in `social/`.
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

## Semi-Automatic Social Distribution

The system generates platform-specific drafts in `social/`:

- `social/zhihu/`: Zhihu long-form version
- `social/toutiao/`: Toutiao article version
- `social/xiaohongshu/`: Xiaohongshu card copy
- `social/short/`: short post for X/Jike/Weibo-style channels

These files are for manual copy/paste publishing. They are not posted automatically.

## Article Drafts

The system can automatically generate HTML drafts in `drafts/`. These drafts are not published SEO pages because they include `noindex,nofollow`.

Use them as a starting point:

1. Edit a draft with real testing notes, screenshots, pricing, and final recommendations.
2. Move the finished article to a public article URL.
3. Link it from `reviews.html`.
4. Run `python3 scripts/seo_system.py --write` so sitemap and reports update.
