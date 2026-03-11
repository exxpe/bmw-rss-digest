#!/usr/bin/env python3
"""
BMW RSS Digest
Fetches RSS feeds, filters by keywords, saves a Markdown digest.

Usage:
  python3 bmw_rss_digest.py                  # run digest
  python3 bmw_rss_digest.py --add-feed URL "Name"   # add a new feed
  python3 bmw_rss_digest.py --add-keyword word      # add a keyword
  python3 bmw_rss_digest.py --remove-keyword word   # remove a keyword
  python3 bmw_rss_digest.py --list                  # show current config
"""

import json
import sys
import os
import ssl
import argparse
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

# macOS fix: bypass SSL certificate verification
ssl._create_default_https_context = ssl._create_unverified_context

# ── Config ────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = SCRIPT_DIR / "bmw_rss_config.json"

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"Config saved: {CONFIG_PATH}")

# ── Fetch & Parse ─────────────────────────────────────────────────────────────

NAMESPACES = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc":      "http://purl.org/dc/elements/1.1/",
}

def fetch_feed(url):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; BMW-RSS-Digest/1.0)"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {url}")
        return None
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return None

def parse_date(date_str):
    """Parse RSS pubDate (RFC 2822) to datetime."""
    if not date_str:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%a, %d %b %Y %H:%M:%S +0000",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None

def parse_rss(xml_bytes, feed_name):
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        print(f"  XML parse error: {e}")
        return items

    channel = root.find("channel")
    if channel is None:
        return items

    for item in channel.findall("item"):
        title       = (item.findtext("title") or "").strip()
        link        = (item.findtext("link") or "").strip()
        pub_date    = item.findtext("pubDate")
        description = (item.findtext("description") or "").strip()
        author      = (item.findtext("{http://purl.org/dc/elements/1.1/}creator") or "").strip()

        # strip HTML tags from description
        import re
        description = re.sub(r"<[^>]+>", "", description).strip()
        description = description[:300] + "…" if len(description) > 300 else description

        items.append({
            "feed":        feed_name,
            "title":       title,
            "link":        link,
            "date":        parse_date(pub_date),
            "date_str":    pub_date or "",
            "description": description,
            "author":      author,
        })
    return items

# ── Filter ────────────────────────────────────────────────────────────────────

def matches_keywords(item, keywords):
    text = " ".join([
        item.get("title", ""),
        item.get("description", ""),
    ]).lower()
    return any(kw.lower() in text for kw in keywords)

def is_recent(item, max_age_days):
    dt = item.get("date")
    if dt is None:
        return True  # include if date unknown
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt) <= timedelta(days=max_age_days)

# ── Output ────────────────────────────────────────────────────────────────────

def render_markdown(matched, all_count, config):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    keywords = config["keywords"]
    max_age  = config["max_age_days"]

    lines = [
        f"# BMW RSS Digest",
        f"**Generated:** {now_str}  ",
        f"**Period:** last {max_age} days  ",
        f"**Keywords:** {', '.join(f'`{k}`' for k in keywords)}  ",
        f"**Matched:** {len(matched)} of {all_count} items across {len(config['feeds'])} feeds",
        "",
        "---",
        "",
    ]

    if not matched:
        lines.append("_No matching items found._")
        return "\n".join(lines)

    # group by feed
    from collections import defaultdict
    by_feed = defaultdict(list)
    for item in matched:
        by_feed[item["feed"]].append(item)

    for feed_name, items in by_feed.items():
        lines.append(f"## {feed_name}")
        lines.append("")
        for item in items:
            date_display = item["date"].strftime("%Y-%m-%d") if item["date"] else "unknown date"
            lines.append(f"### [{item['title']}]({item['link']})")
            meta_parts = [f"📅 {date_display}"]
            if item["author"]:
                meta_parts.append(f"👤 {item['author']}")
            lines.append("  ".join(meta_parts))
            if item["description"]:
                lines.append("")
                lines.append(f"> {item['description']}")
            lines.append("")

    return "\n".join(lines)

# ── Main ──────────────────────────────────────────────────────────────────────

def run_digest(config):
    output_dir = Path(config["output_dir"]).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    keywords    = config["keywords"]
    max_age     = config["max_age_days"]
    all_items   = []
    matched     = []

    for feed in config["feeds"]:
        url  = feed["url"]
        name = feed["name"]
        print(f"Fetching: {name}")
        raw = fetch_feed(url)
        if raw is None:
            continue
        items = parse_rss(raw, name)
        recent = [i for i in items if is_recent(i, max_age)]
        hits   = [i for i in recent if matches_keywords(i, keywords)]
        all_items.extend(recent)
        matched.extend(hits)
        print(f"  {len(recent)} recent items, {len(hits)} matched")

    # sort by date descending
    matched.sort(key=lambda x: x["date"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    md = render_markdown(matched, len(all_items), config)

    filename = f"bmw_digest_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    out_path = output_dir / filename
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"\n✅ Digest saved: {out_path}")
    print(f"   {len(matched)} matching items out of {len(all_items)} total")
    return out_path

def cmd_list(config):
    print("\n── Feeds ──────────────────────────────────────")
    for i, f in enumerate(config["feeds"], 1):
        print(f"  {i}. {f['name']}")
        print(f"     {f['url']}")
    print("\n── Keywords ───────────────────────────────────")
    print("  " + ", ".join(config["keywords"]))
    print(f"\n── Settings ───────────────────────────────────")
    print(f"  Output dir : {config['output_dir']}")
    print(f"  Max age    : {config['max_age_days']} days")

def cmd_add_feed(config, url, name):
    # check duplicate
    for f in config["feeds"]:
        if f["url"] == url:
            print(f"Feed already exists: {name}")
            return
    config["feeds"].append({"url": url, "name": name})
    save_config(config)
    print(f"Added feed: {name}")

def cmd_add_keyword(config, word):
    if word.lower() in [k.lower() for k in config["keywords"]]:
        print(f"Keyword already exists: {word}")
        return
    config["keywords"].append(word)
    save_config(config)
    print(f"Added keyword: {word}")

def cmd_remove_keyword(config, word):
    before = len(config["keywords"])
    config["keywords"] = [k for k in config["keywords"] if k.lower() != word.lower()]
    if len(config["keywords"]) < before:
        save_config(config)
        print(f"Removed keyword: {word}")
    else:
        print(f"Keyword not found: {word}")

def main():
    parser = argparse.ArgumentParser(
        description="BMW RSS Digest — fetch, filter, summarize"
    )
    parser.add_argument("--add-feed",      nargs=2, metavar=("URL", "NAME"),
                        help="Add a new RSS feed")
    parser.add_argument("--add-keyword",   metavar="WORD",
                        help="Add a filter keyword")
    parser.add_argument("--remove-keyword",metavar="WORD",
                        help="Remove a filter keyword")
    parser.add_argument("--list",          action="store_true",
                        help="Show current config")
    args = parser.parse_args()

    config = load_config()

    if args.list:
        cmd_list(config)
    elif args.add_feed:
        cmd_add_feed(config, args.add_feed[0], args.add_feed[1])
    elif args.add_keyword:
        cmd_add_keyword(config, args.add_keyword)
    elif args.remove_keyword:
        cmd_remove_keyword(config, args.remove_keyword)
    else:
        run_digest(config)

if __name__ == "__main__":
    main()
