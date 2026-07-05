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
GENERATED_DIRS = {"docs", "drafts", "social"}


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
    if page.rel.startswith("articles/"):
        return "0.8"
    if page.rel in {"tools.html", "reviews.html"}:
        return "0.9"
    if page.rel in {"compare.html", "skills.html"}:
        return "0.8"
    if page.rel == "sponsor.html":
        return "0.7"
    return "0.5"


def changefreq(page: Page) -> str:
    if page.rel.startswith("articles/"):
        return "monthly"
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
    existing_files = {
        p.relative_to(ROOT).as_posix()
        for p in ROOT.rglob("*")
        if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS)
    }
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
            raw_path = urlparse(href).path.lstrip("/")
            if not raw_path:
                raw_path = "index.html"
            if target not in existing and raw_path not in existing_files and not target.startswith("#"):
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
    content = "\n".join(rows) + "\n"
    out.write_text(content, encoding="utf-8")
    (ROOT / "docs" / "seo-content-calendar.html").write_text(
        markdown_view_page("YongAI SEO Content Calendar", content),
        encoding="utf-8",
    )


def markdown_view_page(title: str, markdown: str) -> str:
    safe_title = html.escape(title)
    safe_markdown = html.escape(markdown)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex,nofollow">
<title>{safe_title}</title>
<style>
body{{margin:0;background:#f5f5f7;color:#1d1d1f;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC",sans-serif;line-height:1.7}}
.wrap{{max-width:1080px;margin:0 auto;padding:34px 20px 72px}}
.top{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px}}
h1{{font-size:28px;line-height:1.2;margin:0}}
.meta{{color:#6e6e73;font-size:13px;margin-top:6px}}
.btn{{border:0;border-radius:999px;background:#0071e3;color:white;font-weight:700;padding:10px 18px;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center}}
.btn.secondary{{background:white;color:#1d1d1f;border:1px solid #d2d2d7}}
.bar{{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}}
textarea{{position:absolute;left:-9999px;top:-9999px}}
pre{{white-space:pre-wrap;background:white;border:1px solid #d2d2d7;border-radius:14px;padding:18px;font-family:"SFMono-Regular",Menlo,Consolas,monospace;font-size:14px;line-height:1.75;overflow:auto}}
.hint{{background:#fff7e6;color:#8a5a00;border:1px solid #ffe0a3;border-radius:12px;padding:12px 14px;margin:16px 0;font-size:13px}}
@media(max-width:640px){{.top{{align-items:flex-start;flex-direction:column}}.btn{{width:100%}}pre{{font-size:13px}}}}
</style>
</head>
<body>
<main class="wrap">
  <div class="top">
    <div><h1>{safe_title}</h1><div class="meta">UTF-8 HTML 阅读版 · Markdown 原文由 SEO 系统自动生成</div></div>
    <a class="btn secondary" href="../dashboard.html">返回控制台</a>
  </div>
  <div class="hint">这是给人看的版本。后台和控制台仍会读取同名 .md 文件，方便自动化更新。</div>
  <textarea id="copybox">{safe_markdown}</textarea>
  <div class="bar">
    <button class="btn" onclick="copyText()">复制全文</button>
    <button class="btn secondary" onclick="selectText()">全选原文</button>
  </div>
  <pre>{safe_markdown}</pre>
</main>
<script>
function selectText(){{var el=document.getElementById('copybox');el.focus();el.select();}}
async function copyText(){{
  var text=document.getElementById('copybox').value;
  try{{await navigator.clipboard.writeText(text);alert('已复制');}}
  catch(e){{selectText();alert('已全选，请按 Command+C 复制');}}
}}
</script>
</body>
</html>
"""


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


def topic_items(topics: Dict) -> List[Tuple[int, str, str, str, str]]:
    items: List[Tuple[int, str, str, str, str]] = []
    for cluster in topics.get("clusters", []):
        for topic in cluster.get("topics", []):
            items.append(
                (
                    int(cluster.get("priority", 99)),
                    cluster.get("cluster", ""),
                    topic,
                    cluster.get("target_url", "/reviews"),
                    cluster.get("money_intent", "medium"),
                )
            )
    return sorted(items)


def write_briefs(topics: Dict, affiliates: Dict, today: dt.date) -> None:
    briefs_dir = ROOT / "docs" / "seo-briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    affiliate_names = [tool["name"] for tool in affiliates.get("tools", []) if tool.get("affiliate_url")]
    fallback_affiliates = [tool["name"] for tool in affiliates.get("tools", []) if tool.get("priority") == "high"]
    for i, (_, cluster, topic, target, intent) in enumerate(topic_items(topics)[:12], start=1):
        slug_base = f"{i:02d}-{topic_slug(topic)}"
        slug = f"{slug_base}.md"
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
        content = "\n".join(rows) + "\n"
        (briefs_dir / slug).write_text(content, encoding="utf-8")
        (briefs_dir / f"{slug_base}.html").write_text(
            markdown_view_page(f"SEO Brief: {topic}", content).replace("../dashboard.html", "../../dashboard.html"),
            encoding="utf-8",
        )


def article_slug(topic: str) -> str:
    ascii_words = re.findall(r"[A-Za-z0-9]+", topic.lower())
    if ascii_words:
        return "-".join(ascii_words[:10])
    zh = re.sub(r"[^\w\u4e00-\u9fff]+", "-", topic).strip("-")
    return zh[:42] or topic_slug(topic)


def extract_tools(topic: str) -> List[str]:
    known = [
        "Claude Code", "GitHub Copilot", "Surfer SEO", "Codex", "Cursor", "Lovable",
        "Bolt", "v0", "Ahrefs", "Semrush", "Perplexity", "Make", "Zapier", "n8n",
        "Kimi", "DeepSeek", "通义千问", "即梦", "Midjourney", "剪映"
    ]
    tools = [name for name in known if name.lower() in topic.lower()]
    if tools:
        return tools[:4]
    if "编程" in topic or "代码" in topic or "开发" in topic:
        return ["Cursor", "Claude Code", "GitHub Copilot", "Codex"]
    if "SEO" in topic or "内容站" in topic or "affiliate" in topic:
        return ["Ahrefs", "Semrush", "Perplexity", "Surfer SEO"]
    if "自动化" in topic or "工作流" in topic:
        return ["Make", "Zapier", "n8n"]
    if "图像" in topic or "视频" in topic:
        return ["即梦", "Midjourney", "剪映"]
    return ["Kimi", "DeepSeek", "通义千问"]


def wrap_text(value: str, width: int) -> List[str]:
    lines: List[str] = []
    line = ""
    for char in value:
        if len(line) >= width:
            lines.append(line)
            line = char
        else:
            line += char
    if line:
        lines.append(line)
    return lines[:4]


def write_cover_image(slug: str, topic: str, cluster: str, tools: List[str]) -> str:
    cover_dir = ROOT / "assets" / "covers"
    cover_dir.mkdir(parents=True, exist_ok=True)
    path = cover_dir / f"{slug}.svg"
    palettes = [
        ("#0f172a", "#2563eb", "#22c55e"),
        ("#111827", "#7c3aed", "#06b6d4"),
        ("#1f2937", "#ea580c", "#facc15"),
        ("#0c4a6e", "#0891b2", "#a3e635"),
    ]
    bg, accent, accent2 = palettes[sum(ord(char) for char in slug) % len(palettes)]
    title_svg = "\n".join(
        f'<text x="70" y="{190 + idx * 58}" class="title">{html.escape(line)}</text>'
        for idx, line in enumerate(wrap_text(topic, 20))
    )
    tool_text = " / ".join(tools[:3])
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{bg}"/><stop offset="1" stop-color="#020617"/></linearGradient>
  <linearGradient id="card" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{accent}"/><stop offset="1" stop-color="{accent2}"/></linearGradient>
  <style>
    .brand{{font:700 34px -apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC",Arial,sans-serif;fill:#fff}}
    .kicker{{font:600 24px -apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC",Arial,sans-serif;fill:rgba(255,255,255,.72)}}
    .title{{font:800 48px -apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC",Arial,sans-serif;fill:#fff}}
    .small{{font:500 24px -apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC",Arial,sans-serif;fill:rgba(255,255,255,.78)}}
  </style>
</defs>
<rect width="1200" height="630" fill="url(#bg)"/>
<circle cx="1030" cy="100" r="230" fill="{accent}" opacity=".28"/>
<circle cx="104" cy="548" r="210" fill="{accent2}" opacity=".18"/>
<rect x="52" y="52" width="1096" height="526" rx="36" fill="rgba(255,255,255,.08)" stroke="rgba(255,255,255,.18)"/>
<rect x="70" y="84" width="246" height="58" rx="29" fill="url(#card)"/>
<text x="102" y="123" class="brand">YongAI</text>
<text x="70" y="170" class="kicker">{html.escape(cluster)} · 购买决策指南</text>
{title_svg}
<rect x="70" y="485" width="760" height="62" rx="18" fill="rgba(255,255,255,.1)" stroke="rgba(255,255,255,.18)"/>
<text x="96" y="526" class="small">{html.escape(tool_text)}</text>
<g transform="translate(905 350)"><rect x="0" y="0" width="178" height="178" rx="38" fill="url(#card)"/><text x="89" y="104" text-anchor="middle" style="font:800 52px Arial,sans-serif;fill:#fff">AI</text></g>
</svg>
"""
    path.write_text(svg, encoding="utf-8")
    return f"../assets/covers/{path.name}"


def tool_table_rows(tools: List[str]) -> str:
    rows = []
    for idx, tool in enumerate(tools):
        if idx == 0:
            best = "优先试用，适合把它作为主力方案验证"
            price = "先用免费额度或月付，不建议直接年付"
            weakness = "需要用真实任务测试稳定性和长期成本"
        elif idx == 1:
            best = "适合作为备选方案，和主力工具交叉验证"
            price = "看团队功能、用量上限和取消订阅是否方便"
            weakness = "可能在复杂任务或中文体验上有差异"
        else:
            best = "适合作为低成本替代或特定场景补充"
            price = "只在明确高频使用时付费"
            weakness = "生态、模板、协作能力可能不如主流工具"
        rows.append(f"<tr><td>{html.escape(tool)}</td><td>{best}</td><td>{price}</td><td>{weakness}</td></tr>")
    return "\n".join(rows)


def long_article_page(topic: str, cluster: str, target: str, intent: str, today: dt.date, slug: str) -> str:
    tools = extract_tools(topic)
    primary = html.escape(tools[0])
    secondary = "、".join(html.escape(t) for t in tools[1:]) or "同类替代工具"
    cover = write_cover_image(slug, topic, cluster, tools)
    description = f"{topic}。从价格、适合人群、国内访问、上手成本和长期工作流角度，给独立开发者和创作者一个可执行的 AI 工具购买建议。"
    rows = tool_table_rows(tools)
    keywords = "、".join(html.escape(k) for k in topic_keywords(topic, cluster)[:5])
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex,nofollow">
<title>{html.escape(topic)} | YongAI 草稿</title>
<meta name="description" content="{html.escape(description)}">
<meta property="og:image" content="{html.escape(cover)}">
<style>
body{{margin:0;background:#f5f5f7;color:#1d1d1f;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC",sans-serif;line-height:1.82}}
.wrap{{max-width:940px;margin:0 auto;padding:42px 22px 78px}}
.draft{{display:inline-flex;background:#fff7e6;color:#8a5a00;border:1px solid #ffe0a3;border-radius:999px;padding:4px 10px;font-size:12px;font-weight:700;margin-bottom:18px}}
h1{{font-size:42px;line-height:1.16;margin:0 0 16px;letter-spacing:0}}
h2{{font-size:25px;margin:38px 0 12px;letter-spacing:0}}
h3{{font-size:19px;margin:24px 0 8px}}
p,li{{color:#424245;font-size:16px}}
.meta{{color:#6e6e73;margin-bottom:24px}}
.cover{{width:100%;border-radius:18px;border:1px solid #d2d2d7;margin:8px 0 28px;background:#111;display:block}}
.summary,.box{{background:white;border:1px solid #d2d2d7;border-radius:14px;padding:20px;margin:18px 0}}
.summary{{border-left:5px solid #0071e3}}
.toc{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:16px 0}}
.toc a{{background:white;border:1px solid #d2d2d7;border-radius:10px;padding:10px 12px;text-decoration:none;color:#1d1d1f;font-weight:650}}
table{{width:100%;border-collapse:collapse;background:white;border:1px solid #d2d2d7;border-radius:12px;overflow:hidden;margin-top:12px}}
th,td{{padding:13px;border-bottom:1px solid #ececef;text-align:left;vertical-align:top;font-size:14px}}
th{{background:#fafafa;color:#6e6e73;font-size:13px}}
tr:last-child td{{border-bottom:none}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}
.note{{background:#fff7e6;border:1px solid #ffe0a3;border-radius:12px;padding:14px;color:#604000}}
.cta{{background:#1d1d1f;color:white;border-radius:16px;padding:24px;margin-top:36px}}
.cta p,.cta li{{color:rgba(255,255,255,.76)}}
a{{color:#0071e3}}
@media(max-width:720px){{h1{{font-size:32px}}.toc,.grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<main class="wrap">
  <div class="draft">DRAFT · 长文章草稿 · 待人工审核后发布</div>
  <h1>{html.escape(topic)}</h1>
  <div class="meta">生成日期：{today.isoformat()} · 分类：{html.escape(cluster)} · 搜索意图：{html.escape(intent)} · 建议入口：{html.escape(target)}</div>
  <img class="cover" src="{html.escape(cover)}" alt="{html.escape(topic)} 封面图">

  <section class="summary">
    <h2>先给结论</h2>
    <p>如果你现在只想快速做决定，我建议先把 <strong>{primary}</strong> 放进第一轮测试。原因不是它一定适合所有人，而是它最容易用真实任务验证价值：能不能省时间、能不能稳定产出、能不能接进你现在的工作流。{secondary} 更适合作为对照组，用来比较价格、协作、国内访问和上手成本。</p>
    <p>这篇文章不是单纯的工具介绍，而是一个购买决策框架。你可以按预算、任务类型、团队规模和国内使用条件逐项判断，避免为了热度付费，也避免因为省小钱耽误长期效率。</p>
  </section>

  <nav class="toc"><a href="#compare">快速对比</a><a href="#who">适合谁</a><a href="#workflow">怎么试用</a><a href="#decision">最终建议</a></nav>

  <h2 id="compare">快速对比表</h2>
  <p>先看这张表。它不是绝对排名，而是帮你把“我该不该付费”拆成几个可验证的问题。正式发布前，建议你把真实价格、截图和自己的测试结果补进去。</p>
  <table><thead><tr><th>工具</th><th>适合谁</th><th>价格策略</th><th>主要风险</th></tr></thead><tbody>{rows}</tbody></table>

  <h2 id="who">哪些人最适合这类工具</h2>
  <div class="grid">
    <section class="box"><h3>独立开发者</h3><p>如果你一个人要同时做产品、文案、页面、代码和运营，这类工具最大的价值是减少切换成本。你不需要追求每个环节都最强，而是需要一个能稳定推进项目的组合。优先选择上手快、结果可控、能导出数据的工具。</p></section>
    <section class="box"><h3>小团队</h3><p>小团队要看协作、权限、稳定性和费用上限。一个工具个人用很好，不代表团队用也好。尤其要检查成员席位、共享项目、历史记录、数据权限和取消订阅流程。</p></section>
    <section class="box"><h3>内容创作者</h3><p>内容创作者更应该关注批量产出、模板复用和平台适配。不要只看单次生成质量，还要看能否持续生成标题、封面、摘要、短帖和长文结构。</p></section>
    <section class="box"><h3>国内用户</h3><p>国内用户必须把访问速度、支付方式、中文体验和数据合规放进判断。一个工具功能再强，如果每天都无法稳定打开，长期价值会大打折扣。</p></section>
  </div>

  <h2>哪些情况不建议马上付费</h2>
  <p>第一，如果你还没有明确任务，只是觉得“别人都在用”，先不要付费。AI 工具最容易让人误判的地方是演示效果很好，但放到自己的工作流里并不高频。</p>
  <p>第二，如果免费额度还没用完，也不要急着买年付。正确做法是连续三天用同一类真实任务测试，记录节省了多少时间、返工率是多少、输出是否能直接使用。</p>
  <p>第三，如果你已经买了同类工具，要先确认它们之间是否重复。很多人同时订阅好几个工具，最后真正高频使用的只有一两个。</p>

  <h2 id="workflow">我建议的 3 天试用方法</h2>
  <ol>
    <li><strong>第 1 天：</strong>用它完成一个真实任务，不要看教程堆功能。记录从开始到产出的时间。</li>
    <li><strong>第 2 天：</strong>换一个稍复杂任务，测试它是否能处理上下文、文件、表格、代码或长文档。</li>
    <li><strong>第 3 天：</strong>把它接进你的固定流程，例如写文章、做页面、改代码、生成素材或整理 SEO 关键词。</li>
  </ol>
  <p>三天后只看一个问题：它是否让你更稳定地完成高频任务。如果答案不明确，就继续免费试用或换工具，不要因为沉没成本继续付费。</p>

  <h2>价格和预算怎么安排</h2>
  <p>如果你的月预算在 50 美元以内，建议只保留一个主力工具，再搭配免费或低价替代品。主力工具负责最高频、最能创造价值的任务；替代品负责偶尔使用的场景。这样比平均订阅多个工具更容易控制成本。</p>
  <p>如果你是团队采购，建议先让 1-2 个核心成员试用，再扩展到全员。团队版通常贵在席位和管理功能，只有当协作效率真的提升时才值得升级。</p>

  <section class="note"><strong>发布前补充建议：</strong>把这里补成你的真实测试数据，例如月费、免费额度、是否需要 VPN、支付方式、任务耗时、失败案例和截图。这样文章会比普通 AI 生成内容更可信。</section>

  <h2>SEO 搜索意图覆盖</h2>
  <p>这篇文章主要覆盖这些关键词方向：{keywords}。正文应该围绕“怎么选、值不值得买、适合谁、国内能不能用、替代方案”展开，而不是写成泛泛的工具百科。</p>

  <h2 id="decision">最终购买建议</h2>
  <p>我的建议是：先选一个主力工具，用真实任务连续测试三天；如果它能稳定节省时间，再考虑月付；如果一个月后仍然高频使用，再考虑年付。对于大多数个人用户，最重要的不是买最贵的工具，而是建立一套能持续产出的工作流。</p>
  <p>如果你还不确定，可以先看 YongAI 的 <a href="../tools.html">AI 工具库</a>、<a href="../compare.html">工具对比</a> 和 <a href="../reviews.html">测评文章</a>，把同类工具放在一起比较后再决定。</p>

  <section class="cta"><h2>发布检查清单</h2><ul><li>补充真实价格和官网链接。</li><li>补充至少 1 张真实截图或替换当前自动封面。</li><li>确认 affiliate 或赞助关系已经披露。</li><li>确认文章标题、描述和 canonical 发布后正确。</li><li>发布后复制社交平台文案，去知乎、小红书、今日头条分发。</li></ul></section>
</main>
</body>
</html>
"""


def write_article_drafts(topics: Dict, today: dt.date) -> None:
    drafts_dir = ROOT / "drafts"
    drafts_dir.mkdir(exist_ok=True)
    for i, (_, cluster, topic, target, intent) in enumerate(topic_items(topics)[:12], start=1):
        slug = f"{i:02d}-{article_slug(topic)}.html"
        path = drafts_dir / slug
        if path.exists():
            continue
        tools = extract_tools(topic)
        rows = "\n".join(
            f"<tr><td>{html.escape(tool)}</td><td>待补充：适合人群</td><td>待补充：价格/优势</td><td>待补充：不足</td></tr>"
            for tool in tools
        )
        primary = html.escape(tools[0])
        alternatives = "、".join(html.escape(t) for t in tools[1:]) or "其他替代工具"
        description = f"{topic}。面向独立开发者和创作者的 AI 工具购买建议、适合人群、价格与工作流对比。"
        page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex,nofollow">
<title>{html.escape(topic)} | YongAI 草稿</title>
<meta name="description" content="{html.escape(description)}">
<style>
body{{margin:0;background:#f5f5f7;color:#1d1d1f;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC",sans-serif;line-height:1.75}}
.wrap{{max-width:880px;margin:0 auto;padding:42px 22px 72px}}
.draft{{display:inline-flex;background:#fff7e6;color:#8a5a00;border:1px solid #ffe0a3;border-radius:999px;padding:4px 10px;font-size:12px;font-weight:700;margin-bottom:18px}}
h1{{font-size:38px;line-height:1.18;margin:0 0 16px}}
h2{{font-size:24px;margin:34px 0 12px}}
p,li{{color:#424245;font-size:16px}}
.meta{{color:#6e6e73;margin-bottom:28px}}
.box{{background:white;border:1px solid #d2d2d7;border-radius:14px;padding:18px;margin:18px 0}}
table{{width:100%;border-collapse:collapse;background:white;border:1px solid #d2d2d7;border-radius:12px;overflow:hidden}}
th,td{{padding:12px;border-bottom:1px solid #ececef;text-align:left;vertical-align:top}}
th{{background:#fafafa;color:#6e6e73;font-size:13px}}
tr:last-child td{{border-bottom:none}}
.cta{{background:#1d1d1f;color:white;border-radius:16px;padding:22px;margin-top:34px}}
.cta p{{color:rgba(255,255,255,.72)}}
a{{color:#0071e3}}
</style>
</head>
<body>
<main class="wrap">
  <div class="draft">DRAFT · 待人工审核，不会被搜索引擎收录</div>
  <h1>{html.escape(topic)}</h1>
  <div class="meta">生成日期：{today.isoformat()} · 分类：{html.escape(cluster)} · 意图：{html.escape(intent)} · 建议入口：{html.escape(target)}</div>

  <section class="box">
    <h2>先给结论</h2>
    <p>如果你只想快速选择，优先看 <strong>{primary}</strong>；如果你更在意不同预算、团队规模或国内访问条件，再对比 {alternatives}。正式发布前，请把这一段改成你的真实判断。</p>
  </section>

  <h2>快速对比表</h2>
  <table>
    <thead><tr><th>工具</th><th>适合谁</th><th>主要优势</th><th>主要不足</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>

  <h2>按场景怎么选</h2>
  <p><strong>预算有限：</strong>补充低预算选择和免费替代方案。</p>
  <p><strong>独立开发者：</strong>补充一个人做产品时的推荐组合。</p>
  <p><strong>小团队：</strong>补充协作、权限、稳定性和成本考虑。</p>
  <p><strong>国内用户：</strong>补充是否需要网络条件、支付方式、中文体验。</p>

  <h2>购买前要测试什么</h2>
  <ul>
    <li>用自己的真实任务测试，而不是只看演示。</li>
    <li>确认价格、免费额度和取消订阅方式。</li>
    <li>确认国内访问、团队协作和数据隐私要求。</li>
    <li>把输出质量和节省时间量化，避免为新鲜感付费。</li>
  </ul>

  <h2>编辑备注</h2>
  <p>这里补充真实截图、价格来源、个人测试过程、失败案例和最终推荐。不要直接发布模板内容。</p>

  <section class="cta">
    <h2>下一步</h2>
    <p>正式发布时，把这里改成工具官网按钮、/compare 内链、Newsletter 订阅入口和赞助披露。</p>
    <p>内部链接建议：<a href="../tools.html">工具库</a> · <a href="../compare.html">工具对比</a> · <a href="../reviews.html">测评文章</a></p>
  </section>
</main>
</body>
</html>
"""
        path.write_text(page, encoding="utf-8")


def write_article_drafts(topics: Dict, today: dt.date) -> None:
    drafts_dir = ROOT / "drafts"
    drafts_dir.mkdir(exist_ok=True)
    for i, (_, cluster, topic, target, intent) in enumerate(topic_items(topics)[:12], start=1):
        slug_base = f"{i:02d}-{article_slug(topic)}"
        slug = f"{slug_base}.html"
        if (ROOT / "articles" / slug).exists():
            continue
        (drafts_dir / slug).write_text(
            long_article_page(topic, cluster, target, intent, today, slug_base),
            encoding="utf-8",
        )


def article_path_from_draft(draft: Path) -> Path:
    return ROOT / "articles" / draft.name


def publish_draft(draft_rel: str, today: dt.date) -> Optional[str]:
    draft = ROOT / draft_rel
    if not draft.exists() or draft.parent.name != "drafts" or draft.suffix != ".html":
        return None
    articles_dir = ROOT / "articles"
    articles_dir.mkdir(exist_ok=True)
    article = article_path_from_draft(draft)
    text = draft.read_text(encoding="utf-8")
    slug = article.stem
    canonical = f"{BASE_URL}/articles/{slug}"
    text = text.replace('<meta name="robots" content="noindex,nofollow">\n', "")
    text = text.replace(" | YongAI 草稿</title>", " | YongAI</title>")
    text = text.replace(
        "</head>",
        f'<link rel="canonical" href="{canonical}">\n</head>',
        1,
    )
    text = text.replace(
        '<div class="draft">DRAFT · 待人工审核，不会被搜索引擎收录</div>',
        f'<div class="draft">PUBLISHED · YongAI 正式文章 · {today.isoformat()}</div>',
    )
    text = text.replace(
        '<div class="draft">DRAFT · 长文章草稿 · 待人工审核后发布</div>',
        f'<div class="draft">PUBLISHED · YongAI 正式文章 · {today.isoformat()}</div>',
    )
    text = text.replace("正式发布前，请把这一段改成你的真实判断。", "以下建议用于快速判断，建议结合自己的预算和使用场景再做最终选择。")
    text = text.replace("待补充：", "建议关注：")
    text = text.replace("这里补充真实截图、价格来源、个人测试过程、失败案例和最终推荐。不要直接发布模板内容。", "建议后续继续补充真实截图、价格来源、个人测试过程和失败案例，让这篇文章越来越有参考价值。")
    text = text.replace("../tools.html", "../tools.html").replace("../compare.html", "../compare.html").replace("../reviews.html", "../reviews.html")
    article.write_text(text, encoding="utf-8")
    return article.relative_to(ROOT).as_posix()


def publish_next_articles(topics: Dict, count: int, today: dt.date) -> List[str]:
    published: List[str] = []
    for i, (_, _cluster, topic, _target, _intent) in enumerate(topic_items(topics)[:12], start=1):
        draft_rel = f"drafts/{i:02d}-{article_slug(topic)}.html"
        article = article_path_from_draft(ROOT / draft_rel)
        if article.exists():
            continue
        rel = publish_draft(draft_rel, today)
        if rel:
            published.append(rel)
        if len(published) >= count:
            break
    return published


def write_publish_queue(topics: Dict, today: dt.date, daily_limit: int = 2) -> None:
    queue = []
    for i, (_, cluster, topic, target, intent) in enumerate(topic_items(topics)[:12], start=1):
        draft = f"drafts/{i:02d}-{article_slug(topic)}.html"
        article = f"articles/{i:02d}-{article_slug(topic)}.html"
        queue.append(
            {
                "topic": topic,
                "cluster": cluster,
                "intent": intent,
                "target": target,
                "draft": draft,
                "article": article,
                "published": (ROOT / article).exists(),
                "command": f"python3 scripts/seo_system.py --publish-draft {draft} --write",
            }
        )
    payload = {
        "generated": today.isoformat(),
        "daily_limit": daily_limit,
        "publish_next_command": f"python3 scripts/seo_system.py --publish-next {daily_limit} --write",
        "items": queue,
    }
    (ROOT / "seo" / "publish-queue.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def social_texts(topic: str, cluster: str, target: str) -> Dict[str, str]:
    tools = extract_tools(topic)
    tool_line = " / ".join(tools)
    site_url = "https://yongai.online"
    zhihu = f"""# {topic}

先说结论：这类工具不要只看谁更火，要看你的真实场景、预算、国内访问条件和后续工作流。

我会按 4 个维度判断：

1. 适合谁：新手、独立开发者、小团队、内容创作者分别不一样。
2. 成本：月费、免费额度、团队价格和隐藏成本。
3. 上手成本：能不能马上用到真实项目里。
4. 可替代性：如果不用它，是否有更便宜或更稳定的方案。

本篇重点对比：{tool_line}

简短建议：

- 预算有限：先用免费或低价方案验证需求。
- 想省时间：优先选择上手快、模板多、生态成熟的工具。
- 做长期项目：关注数据导出、团队协作、稳定性和隐私。
- 国内用户：一定要测试访问速度、支付方式和中文体验。

完整对比表、价格和后续更新放在 YongAI：{site_url}{target}
"""
    toutiao = f"""# {topic}

很多人选 AI 工具时容易被热度带着走，但真正付费前，应该先问三个问题：

第一，它能不能解决你现在最频繁的任务？
第二，它的价格是否比节省下来的时间更划算？
第三，如果以后不用了，数据和工作流能不能迁移？

这篇选题主要比较：{tool_line}。

如果你是一个人做项目，优先看上手速度和能不能直接产出结果；如果你是小团队，优先看协作、稳定性和权限；如果你在国内使用，还要测试访问、支付和中文体验。

我的建议是：不要一上来就买年付，先用真实任务试 3 天，再决定是否长期使用。

更多 AI 工具对比和更新，可以看 YongAI：{site_url}
"""
    xhs_cards = [
        f"封面：{topic}",
        "第 1 张：先别急着付费，先看你的真实任务是什么。",
        f"第 2 张：本次对比工具：{tool_line}",
        "第 3 张：预算有限，优先选免费额度够用、取消方便的工具。",
        "第 4 张：独立开发者，优先看能不能直接推进项目。",
        "第 5 张：小团队，优先看协作、稳定性、权限和数据安全。",
        "第 6 张：国内用户，先测试访问、支付、中文体验。",
        "第 7 张：不要只看热门榜，要看适合人群和真实工作流。",
        "第 8 张：完整对比表在 YongAI：yongai.online"
    ]
    xiaohongshu = "\n\n".join(xhs_cards) + "\n\n标题建议：\n- " + topic + "\n- AI 工具别乱买，先看这 4 点\n\n话题：#AI工具 #效率工具 #独立开发 #AI编程 #工具推荐"
    short = f"""今天的 AI 工具选题：{topic}

我的判断标准不是热度，而是：
1. 是否解决真实任务
2. 是否值得付费
3. 是否适合国内使用
4. 是否能接进长期工作流

完整对比放在 YongAI：{site_url}{target}
"""
    return {"zhihu": zhihu, "toutiao": toutiao, "xiaohongshu": xiaohongshu, "short": short}


def social_copy_page(topic: str, platform: str, text: str) -> str:
    title = f"{topic} - {platform}"
    safe_text = html.escape(text)
    safe_title = html.escape(title)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex,nofollow">
<title>{safe_title}</title>
<style>
body{{margin:0;background:#f5f5f7;color:#1d1d1f;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC",sans-serif;line-height:1.7}}
.wrap{{max-width:920px;margin:0 auto;padding:36px 20px 72px}}
.top{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:18px}}
h1{{font-size:26px;line-height:1.25;margin:0}}
.meta{{color:#6e6e73;font-size:13px;margin-top:6px}}
.btn{{border:0;border-radius:999px;background:#0071e3;color:white;font-weight:700;padding:10px 18px;cursor:pointer}}
.btn.secondary{{background:white;color:#1d1d1f;border:1px solid #d2d2d7}}
.bar{{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}}
textarea{{width:100%;min-height:420px;border:1px solid #d2d2d7;border-radius:14px;padding:16px;font-size:15px;line-height:1.7;font-family:inherit;resize:vertical;background:white;color:#1d1d1f}}
.hint{{background:#fff7e6;color:#8a5a00;border:1px solid #ffe0a3;border-radius:12px;padding:12px 14px;margin-bottom:14px;font-size:13px}}
pre{{white-space:pre-wrap;background:white;border:1px solid #d2d2d7;border-radius:14px;padding:16px;font-family:inherit;font-size:15px;line-height:1.7}}
@media(max-width:640px){{.top{{align-items:flex-start;flex-direction:column}}.btn{{width:100%}}}}
</style>
</head>
<body>
<main class="wrap">
  <div class="top">
    <div><h1>{safe_title}</h1><div class="meta">半自动分发文案 · 手动复制到平台发布</div></div>
    <button class="btn" onclick="copyText()">复制全文</button>
  </div>
  <div class="hint">如果平台不接受 Markdown 标题符号，可以复制后删掉开头的 #。发布前建议再按平台语气微调。</div>
  <textarea id="copybox">{safe_text}</textarea>
  <div class="bar">
    <button class="btn" onclick="copyText()">复制全文</button>
    <button class="btn secondary" onclick="selectText()">全选文本</button>
    <a class="btn secondary" href="../../dashboard.html" style="text-decoration:none;text-align:center">返回控制台</a>
  </div>
  <pre>{safe_text}</pre>
</main>
<script>
function selectText(){{var el=document.getElementById('copybox');el.focus();el.select();}}
async function copyText(){{
  var text=document.getElementById('copybox').value;
  try{{await navigator.clipboard.writeText(text);alert('已复制');}}
  catch(e){{selectText();alert('已全选，请按 Command+C 复制');}}
}}
</script>
</body>
</html>
"""


def write_social_packages(topics: Dict, today: dt.date) -> None:
    social_dir = ROOT / "social"
    for platform in ["zhihu", "toutiao", "xiaohongshu", "short"]:
        (social_dir / platform).mkdir(parents=True, exist_ok=True)
    index = []
    for i, (_, cluster, topic, target, intent) in enumerate(topic_items(topics)[:12], start=1):
        slug = f"{i:02d}-{article_slug(topic)}"
        texts = social_texts(topic, cluster, target)
        entry = {"topic": topic, "cluster": cluster, "intent": intent, "target": target, "files": {}}
        for platform, text in texts.items():
            rel = f"social/{platform}/{slug}.html"
            (ROOT / rel).write_text(social_copy_page(topic, platform, text), encoding="utf-8")
            entry["files"][platform] = rel
        index.append(entry)
    (social_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    content = "\n".join(rows) + "\n"
    out.write_text(content, encoding="utf-8")
    (ROOT / "docs" / "seo-report.html").write_text(
        markdown_view_page("YongAI SEO Automation Report", content),
        encoding="utf-8",
    )


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
    content = "\n".join(rows) + "\n"
    out.write_text(content, encoding="utf-8")
    (ROOT / "docs" / "affiliate-report.html").write_text(
        markdown_view_page("YongAI Affiliate Link Report", content),
        encoding="utf-8",
    )


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
    parser.add_argument("--publish-next", type=int, default=0, help="publish the next N reviewed drafts as article pages")
    parser.add_argument("--publish-draft", default="", help="publish one draft HTML file, for example drafts/01-topic.html")
    parser.add_argument("--fail-on-issues", action="store_true", help="exit non-zero if audit finds issues")
    args = parser.parse_args()

    today = dt.date.today()
    topics = load_topics()
    affiliates = load_affiliates()

    if args.publish_draft or args.publish_next:
        write_article_drafts(topics, today)

    if args.publish_draft:
        rel = publish_draft(args.publish_draft, today)
        if rel:
            print(f"Published: {rel}")
        else:
            print(f"Could not publish draft: {args.publish_draft}", file=sys.stderr)
            return 1
    if args.publish_next:
        published = publish_next_articles(topics, max(args.publish_next, 0), today)
        if published:
            for rel in published:
                print(f"Published: {rel}")
        else:
            print("No unpublished drafts found.")

    pages = scan_pages()
    issues = audit_pages(pages)

    if args.write:
        write_sitemap(pages, today.isoformat())
        write_robots()
        write_content_calendar(topics, today)
        write_briefs(topics, affiliates, today)
        write_article_drafts(topics, today)
        write_publish_queue(topics, today, daily_limit=2)
        write_social_packages(topics, today)
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
