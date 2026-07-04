#!/usr/bin/env python3
"""Automated SEO maintenance for the YongAI static site.

What it does:
- scans HTML pages for title, description, canonical, robots, headings, and links
- rewrites sitemap.xml from current indexable pages
- rewrites robots.txt with the sitemap location
- generates a weekly content calendar from seo/topics.json
- writes docs/seo-report.md with issues and next actions

It intentionally creates briefs and reports, not low-quality auto-published articles.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://yongai.online"
SKIP_DIRS = {".git", ".github", "node_modules", "__pycache__"}
GENERATED_DIRS = {"docs"}


@dataclass
class Page:
    path: Path
    rel: str
    title: str = ""
    description: str = ""
    canonical: str = ""
    robots: str = ""
    h1: str = ""
    local_links: Tuple[str, ...] = ()

    @property
    def indexable(self) -> bool:
        return "noindex" not in self.robots.lower()

    @property
    def url(self) -> str:
        if self.canonical:
            return self.canonical
        rel = self.rel
        if rel == "index.html":
            return BASE_URL + "/"
        if rel.endswith("/index.html"):
            return BASE_URL + "/" + rel[: -len("index.html")]
        if rel.endswith(".html"):
            return BASE_URL + "/" + rel[: -5]
        return BASE_URL + "/" + rel


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.description = ""
        self.canonical = ""
        self.robots = ""
        self.links: List[str] = []
        self.h1_parts: List[str] = []
        self._in_title = False
        self._in_h1 = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        data = {k.lower(): (v or "") for k, v in attrs}
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._in_h1 = True
        elif tag == "meta":
            name = data.get("name", "").lower()
            prop = data.get("property", "").lower()
            content = data.get("content", "")
            if name == "description" and not self.description:
                self.description = content.strip()
            elif name == "robots":
                self.robots = content.strip()
            elif prop == "og:description" and not self.description:
                self.description = content.strip()
        elif tag == "link" and data.get("rel", "").lower() == "canonical":
            self.canonical = data.get("href", "").strip()
        elif tag == "a":
            href = data.get("href", "").strip()
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
        elif tag.lower() == "h1":
            self._in_h1 = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._in_h1:
            self.h1_parts.append(data)

    @property
    def h1(self) -> str:
        return " ".join(part.strip() for part in self.h1_parts if part.strip())


def should_scan(path: Path) -> bool:
    parts = set(path.relative_to(ROOT).parts)
    if parts & SKIP_DIRS:
        return False
    if parts & GENERATED_DIRS:
        return False
    return path.suffix == ".html"


def parse_page(path: Path) -> Page:
    text = path.read_text(encoding="utf-8", errors="ignore")
    parser = PageParser()
    parser.feed(text)
    rel = path.relative_to(ROOT).as_posix()
    local_links = tuple(link for link in parser.links if is_local_link(link))
    return Page(
        path=path,
        rel=rel,
        title=collapse(parser.title),
        description=collapse(parser.description),
        canonical=parser.canonical,
        robots=parser.robots,
        h1=collapse(parser.h1),
        local_links=local_links,
    )


def collapse(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def is_local_link(href: str) -> bool:
    if href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return False
    parsed = urlparse(href)
    return not parsed.netloc or parsed.netloc == "yongai.online"


def normalize_local_href(href: str, source: Page) -> str:
    parsed = urlparse(href)
    if parsed.netloc == "yongai.online":
        path = parsed.path.lstrip("/")
    else:
        base = source.rel.rsplit("/", 1)[0] + "/" if "/" in source.rel else ""
        path = urljoin(base, parsed.path).lstrip("/")
    if not path or path == ".":
        return "index.html"
    if path.endswith("/"):
        path += "index.html"
    if not Path(path).suffix:
        path += ".html"
    return path


def scan_pages() -> List[Page]:
    return sorted((parse_page(p) for p in ROOT.rglob("*.html") if should_scan(p)), key=lambda p: p.rel)


def page_priority(page: Page) -> str:
    if page.rel == "index.html":
        return "1.0"
    if page.rel in {"tools.html", "reviews.html"}:
        return "0.9"
    if page.rel in {"compare.html", "skills.html"}:
        return "0.8"
    if page.rel == "sponsor.html":
        return "0.7"
    return "0.5"


def changefreq(page: Page) -> str:
    if page.rel in {"index.html", "tools.html", "reviews.html"}:
        return "weekly"
    return "monthly"


def write_sitemap(pages: List[Page], today: str) -> None:
    urls = []
    for page in pages:
        if not page.indexable:
            continue
        urls.append(
            f'    <url><loc>{page.url}</loc><changefreq>{changefreq(page)}</changefreq>'
            f"<priority>{page_priority(page)}</priority><lastmod>{today}</lastmod></url>"
        )
    body = "\n".join(urls)
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n"
        "</urlset>\n",
        encoding="utf-8",
    )


def write_robots() -> None:
    (ROOT / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n\nSitemap: https://yongai.online/sitemap.xml\n",
        encoding="utf-8",
    )


def audit_pages(pages: List[Page]) -> List[str]:
    issues: List[str] = []
    existing = {p.rel for p in pages}
    for page in pages:
        if page.indexable:
            if not page.title:
                issues.append(f"[missing-title] {page.rel} has no <title>.")
            elif len(page.title) > 70:
                issues.append(f"[long-title] {page.rel} title is {len(page.title)} chars.")
            if not page.description:
                issues.append(f"[missing-description] {page.rel} has no meta description.")
            elif len(page.description) < 70:
                issues.append(f"[short-description] {page.rel} description is only {len(page.description)} chars.")
            elif len(page.description) > 180:
                issues.append(f"[long-description] {page.rel} description is {len(page.description)} chars.")
            if not page.canonical:
                issues.append(f"[missing-canonical] {page.rel} has no canonical URL.")
            if not page.h1:
                issues.append(f"[missing-h1] {page.rel} has no visible H1.")
        for href in page.local_links:
            target = normalize_local_href(href, page)
            if target not in existing and not target.startswith("#"):
                issues.append(f"[broken-local-link] {page.rel} links to missing {href} -> {target}.")
    return issues


def load_topics() -> Dict:
    path = ROOT / "seo" / "topics.json"
    if not path.exists():
        return {"clusters": []}
    return json.loads(path.read_text(encoding="utf-8"))


def write_content_calendar(topics: Dict, today: dt.date) -> None:
    rows = [
        "# YongAI SEO Content Calendar",
        "",
        f"Generated: {today.isoformat()}",
        "",
        "This calendar favors high-intent comparison and buying-decision content. Drafts should be reviewed before publishing.",
        "",
        "| Week | Cluster | Topic | Target URL | Intent | CTA |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    week = today
    items: List[Tuple[int, str, str, str, str]] = []
    for cluster in topics.get("clusters", []):
        priority = int(cluster.get("priority", 99))
        for topic in cluster.get("topics", []):
            items.append(
                (
                    priority,
                    cluster.get("cluster", ""),
                    topic,
                    cluster.get("target_url", "/reviews"),
                    cluster.get("money_intent", "medium"),
                )
            )
    for i, (_, cluster, topic, target, intent) in enumerate(sorted(items), start=1):
        publish_week = week + dt.timedelta(days=(i - 1) * 3)
        cta = "affiliate comparison" if intent == "high" else "newsletter + tool directory"
        rows.append(f"| {publish_week.isoformat()} | {cluster} | {topic} | {target} | {intent} | {cta} |")
    out = ROOT / "docs" / "seo-content-calendar.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")


def load_affiliates() -> Dict:
    path = ROOT / "seo" / "affiliate-links.json"
    if not path.exists():
        return {"tools": []}
    return json.loads(path.read_text(encoding="utf-8"))


def topic_slug(topic: str) -> str:
    ascii_words = re.findall(r"[A-Za-z0-9]+", topic.lower())
    if ascii_words:
        return "-".join(ascii_words[:8])
    return "brief-" + str(abs(hash(topic)) % 100000)


def topic_keywords(topic: str, cluster: str) -> List[str]:
    words = [topic]
    if "vs" in topic.lower() or "对比" in topic or "怎么选" in topic:
        words += ["AI 工具对比", "购买建议", "价格对比", "适合人群"]
    if "国内" in topic or "Kimi" in topic or "DeepSeek" in topic:
        words += ["国内可用 AI 工具", "无需 VPN", "中文 AI 工具"]
    if "SEO" in cluster or "SEO" in topic:
        words += ["AI SEO 工具", "内容站工具", "affiliate 内容站"]
    if "编程" in cluster or "Cursor" in topic or "Codex" in topic:
        words += ["AI 编程工具", "独立开发者工具", "代码助手"]
    return words[:8]


def write_briefs(topics: Dict, affiliates: Dict, today: dt.date) -> None:
    briefs_dir = ROOT / "docs" / "seo-briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    affiliate_names = [tool["name"] for tool in affiliates.get("tools", []) if tool.get("affiliate_url")]
    fallback_affiliates = [tool["name"] for tool in affiliates.get("tools", []) if tool.get("priority") == "high"]
    all_items: List[Tuple[int, str, str, str, str]] = []
    for cluster in topics.get("clusters", []):
        for topic in cluster.get("topics", []):
            all_items.append(
                (
                    int(cluster.get("priority", 99)),
                    cluster.get("cluster", ""),
                    topic,
                    cluster.get("target_url", "/reviews"),
                    cluster.get("money_intent", "medium"),
                )
            )
    for i, (_, cluster, topic, target, intent) in enumerate(sorted(all_items)[:12], start=1):
        slug = f"{i:02d}-{topic_slug(topic)}.md"
        cta_tools = affiliate_names or fallback_affiliates[:4] or ["tools directory"]
        rows = [
            f"# SEO Brief: {topic}",
            "",
            f"Generated: {today.isoformat()}",
            "",
            "## Search Intent",
            "",
            "- User wants a buying decision, not a generic introduction.",
            "- Answer who should choose each tool, who should avoid it, and what budget level makes sense.",
            f"- Money intent: {intent}.",
            "",
            "## Target Page",
            "",
            f"- Publish or internally link from: `{target}`",
            "- Add clear affiliate/sponsored disclosure when using commercial links.",
            "",
            "## Primary Keywords",
            "",
        ]
        rows += [f"- {kw}" for kw in topic_keywords(topic, cluster)]
        rows += [
            "",
            "## Recommended Structure",
            "",
            "1. Short answer: give the recommendation in the first 120 words.",
            "2. Comparison table: price, best for, China availability, learning curve, main weakness.",
            "3. Scenario recommendations: beginner, solo builder, small team, budget user.",
            "4. Hands-on notes: what to test before paying.",
            "5. Final CTA: link to the best-fit tool and a relevant comparison page.",
            "",
            "## Monetization CTA",
            "",
            f"- Candidate affiliate tools: {', '.join(cta_tools)}",
            "- Secondary CTA: newsletter signup for weekly AI tool picks.",
            "- Internal links: `/tools`, `/compare`, `/reviews`, `/sponsor`.",
            "",
            "## Quality Bar",
            "",
            "- Do not publish a thin AI-generated roundup.",
            "- Include concrete tradeoffs, prices, domestic access notes, and a clear verdict.",
            "- Mark affiliate or sponsored relationships transparently.",
        ]
        (briefs_dir / slug).write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_report(pages: List[Page], issues: List[str], today: dt.date) -> None:
    indexable = [p for p in pages if p.indexable]
    rows = [
        "# YongAI SEO Automation Report",
        "",
        f"Generated: {today.isoformat()}",
        "",
        "## Summary",
        "",
        f"- Scanned HTML pages: {len(pages)}",
        f"- Indexable pages: {len(indexable)}",
        f"- Issues found: {len(issues)}",
        "",
        "## Indexable Pages",
        "",
        "| Page | Title | Canonical | Description length |",
        "| --- | --- | --- | --- |",
    ]
    for page in indexable:
        rows.append(f"| `{page.rel}` | {escape_md(page.title)} | {page.url} | {len(page.description)} |")
    rows += ["", "## Issues", ""]
    if issues:
        rows += [f"- {issue}" for issue in issues]
    else:
        rows.append("- No blocking SEO issues found.")
    rows += [
        "",
        "## Next Automatic Actions",
        "",
        "- Keep sitemap.xml and robots.txt synchronized with current HTML files.",
        "- Keep the content calendar focused on comparison, buying-intent, and China-availability queries.",
        "- Review generated issues before publishing new pages.",
    ]
    out = ROOT / "docs" / "seo-report.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_affiliate_report(affiliates: Dict, today: dt.date) -> None:
    tools = affiliates.get("tools", [])
    filled = [t for t in tools if t.get("affiliate_url")]
    missing_high = [t for t in tools if not t.get("affiliate_url") and t.get("priority") == "high"]
    rows = [
        "# YongAI Affiliate Link Report",
        "",
        f"Generated: {today.isoformat()}",
        "",
        "## Summary",
        "",
        f"- Tracked tools: {len(tools)}",
        f"- Affiliate links filled: {len(filled)}",
        f"- High-priority missing links: {len(missing_high)}",
        "",
        "## Link Tracker",
        "",
        "| Tool | Category | Priority | Affiliate status |",
        "| --- | --- | --- | --- |",
    ]
    for tool in tools:
        status = "ready" if tool.get("affiliate_url") else "missing"
        rows.append(f"| {tool.get('name','')} | {tool.get('category','')} | {tool.get('priority','')} | {status} |")
    rows += [
        "",
        "## Next Actions",
        "",
    ]
    if missing_high:
        rows += [f"- Apply for or fill affiliate link: {tool.get('name')}" for tool in missing_high]
    else:
        rows.append("- High-priority affiliate links are filled.")
    rows.append("- After adding links, replace the matching tool `url` value in the HTML data block or route outbound clicks through a tracked link layer.")
    out = ROOT / "docs" / "affiliate-report.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_redirects(affiliates: Dict) -> None:
    base_rules = [
        "/sponsor /sponsor.html 200",
        "/submit /sponsor.html 302",
        "/submit.html /sponsor.html 302",
        "/tools /tools.html 200",
        "/reviews /reviews.html 200",
        "/skills /skills.html 200",
        "/compare /compare.html 200",
    ]
    affiliate_rules = []
    for tool in affiliates.get("tools", []):
        url = (tool.get("affiliate_url") or "").strip()
        tool_id = (tool.get("id") or "").strip()
        if tool_id and url:
            affiliate_rules.append(f"/go/{tool_id} {url} 302")
    body = "\n".join(base_rules + affiliate_rules) + "\n"
    (ROOT / "_redirects").write_text(body, encoding="utf-8")


def escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write sitemap, robots, and reports")
    parser.add_argument("--fail-on-issues", action="store_true", help="exit non-zero if audit finds issues")
    args = parser.parse_args()

    today = dt.date.today()
    pages = scan_pages()
    issues = audit_pages(pages)
    topics = load_topics()
    affiliates = load_affiliates()

    if args.write:
        write_sitemap(pages, today.isoformat())
        write_robots()
        write_content_calendar(topics, today)
        write_briefs(topics, affiliates, today)
        write_report(pages, issues, today)
        write_affiliate_report(affiliates, today)
        write_redirects(affiliates)
    else:
        for issue in issues:
            print(issue)

    if args.fail_on_issues and issues:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
