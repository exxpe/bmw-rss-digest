#!/usr/bin/env python3
"""
BMW RSS Digest
Fetches RSS feeds, filters by keywords, saves a Markdown digest.

Usage:
  python3 bmw_rss_digest.py                           # run digest
  python3 bmw_rss_digest.py --from-date 2026-03-01    # filter from date
  python3 bmw_rss_digest.py --to-date   2026-03-13    # filter to date
  python3 bmw_rss_digest.py --add-feed URL "Name"     # add a new feed
  python3 bmw_rss_digest.py --add-keyword word        # add a keyword
  python3 bmw_rss_digest.py --remove-keyword word     # remove a keyword
  python3 bmw_rss_digest.py --list                    # show current config
"""

import json
import sys
import re
import ssl
import argparse
import logging
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# macOS fix: bypass SSL certificate verification
ssl._create_default_https_context = ssl._create_unverified_context

# ── Config ────────────────────────────────────────────────────────────────────

SCRIPT_DIR  = Path(__file__).parent.resolve()
CONFIG_PATH = SCRIPT_DIR / "bmw_rss_config.json"
LOG_PATH    = SCRIPT_DIR / "bmw_rss.log"

logger = logging.getLogger("bmw_rss")


def setup_logging(add_stream_handler: bool = True):
    """Configure file logging with rotation. Safe to call multiple times."""
    if logger.handlers:
        return
    logger.setLevel(logging.DEBUG)

    fh = RotatingFileHandler(
        LOG_PATH, maxBytes=500 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(fh)

    if add_stream_handler:
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(ch)


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    logger.info(f"Config saved: {CONFIG_PATH}")


# ── Fetch & Parse ─────────────────────────────────────────────────────────────

def fetch_feed(url: str) -> Optional[bytes]:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; BMW-RSS-Digest/1.0)"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        logger.warning(f"  HTTP {e.code}: {url}")
        return None
    except Exception as e:
        logger.error(f"  Error fetching {url}: {e}")
        return None


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
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


def parse_rss(xml_bytes: bytes, feed_name: str) -> list:
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        logger.error(f"  XML parse error: {e}")
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

def matches_keywords(item: dict, keywords: list) -> bool:
    text = " ".join([item.get("title", ""), item.get("description", "")]).lower()
    return any(kw.lower() in text for kw in keywords)


def is_in_range(item: dict, cutoff_from: datetime,
                cutoff_to: Optional[datetime] = None) -> bool:
    dt = item.get("date")
    if dt is None:
        return True  # include if date unknown
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if dt < cutoff_from:
        return False
    if cutoff_to and dt > cutoff_to:
        return False
    return True


# ── Output ────────────────────────────────────────────────────────────────────

def render_markdown(matched: list, all_count: int, config: dict,
                    from_date: Optional[datetime] = None,
                    to_date: Optional[datetime] = None) -> str:
    now_str  = datetime.now().strftime("%Y-%m-%d %H:%M")
    keywords = config["keywords"]

    if from_date:
        end = (to_date or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
        period = f"{from_date.strftime('%Y-%m-%d')} → {end}"
    else:
        period = f"last {config['max_age_days']} days"

    lines = [
        "# BMW RSS Digest",
        f"**Generated:** {now_str}  ",
        f"**Period:** {period}  ",
        f"**Keywords:** {', '.join(f'`{k}`' for k in keywords)}  ",
        f"**Matched:** {len(matched)} of {all_count} items across {len(config['feeds'])} feeds",
        "",
        "---",
        "",
    ]

    if not matched:
        lines.append("_No matching items found._")
        return "\n".join(lines)

    by_feed: dict = defaultdict(list)
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


# ── Run ───────────────────────────────────────────────────────────────────────

def run_digest(config: dict,
               from_date: Optional[datetime] = None,
               to_date: Optional[datetime] = None) -> dict:
    """Fetch feeds, filter, save digest. Returns stats dict."""
    output_dir = Path(config["output_dir"]).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    keywords = config["keywords"]
    max_age  = config["max_age_days"]

    # Determine date range
    if from_date is None:
        cutoff_from = datetime.now(timezone.utc) - timedelta(days=max_age)
    else:
        cutoff_from = from_date if from_date.tzinfo else from_date.replace(tzinfo=timezone.utc)

    if to_date is not None and to_date.tzinfo is None:
        to_date = to_date.replace(tzinfo=timezone.utc)

    end_label = (to_date or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    logger.info(f"Starting digest  {cutoff_from.strftime('%Y-%m-%d')} → {end_label}")
    logger.info(f"Keywords ({len(keywords)}): {', '.join(keywords)}")
    logger.info(f"Feeds: {len(config['feeds'])}")
    logger.info("─" * 50)

    all_items: list  = []
    matched: list    = []
    feed_stats: dict = {}

    for feed in config["feeds"]:
        url  = feed["url"]
        name = feed["name"]
        logger.info(f"Fetching: {name}")
        raw = fetch_feed(url)
        if raw is None:
            feed_stats[name] = {"recent": 0, "matched": 0, "error": True}
            continue
        items  = parse_rss(raw, name)
        recent = [i for i in items if is_in_range(i, cutoff_from, to_date)]
        hits   = [i for i in recent if matches_keywords(i, keywords)]
        all_items.extend(recent)
        matched.extend(hits)
        feed_stats[name] = {"recent": len(recent), "matched": len(hits), "error": False}
        logger.info(f"  → {len(recent)} recent,  {len(hits)} matched")

    matched.sort(
        key=lambda x: x["date"] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    md = render_markdown(matched, len(all_items), config, from_date, to_date)

    filename = f"bmw_digest_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    out_path = output_dir / filename
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)

    logger.info("─" * 50)
    logger.info(f"✅ Digest saved: {out_path}")
    logger.info(f"   {len(matched)} matched / {len(all_items)} total")

    return {
        "path":        out_path,
        "matched":     len(matched),
        "total":       len(all_items),
        "feeds_count": len(config["feeds"]),
        "feed_stats":  feed_stats,
        "timestamp":   datetime.now().strftime("%H:%M:%S"),
    }


# ── CLI helpers ───────────────────────────────────────────────────────────────

def cmd_list(config: dict):
    logger.info("── Feeds ──────────────────────────────────────")
    for i, f in enumerate(config["feeds"], 1):
        logger.info(f"  {i}. {f['name']}")
        logger.info(f"     {f['url']}")
    logger.info("── Keywords ───────────────────────────────────")
    logger.info("  " + ", ".join(config["keywords"]))
    logger.info("── Settings ───────────────────────────────────")
    logger.info(f"  Output dir : {config['output_dir']}")
    logger.info(f"  Max age    : {config['max_age_days']} days")


def cmd_add_feed(config: dict, url: str, name: str):
    for f in config["feeds"]:
        if f["url"] == url:
            logger.info(f"Feed already exists: {name}")
            return
    config["feeds"].append({"url": url, "name": name})
    save_config(config)
    logger.info(f"Added feed: {name}")


def cmd_add_keyword(config: dict, word: str):
    if word.lower() in [k.lower() for k in config["keywords"]]:
        logger.info(f"Keyword already exists: {word}")
        return
    config["keywords"].append(word)
    save_config(config)
    logger.info(f"Added keyword: {word}")


def cmd_remove_keyword(config: dict, word: str):
    before = len(config["keywords"])
    config["keywords"] = [k for k in config["keywords"] if k.lower() != word.lower()]
    if len(config["keywords"]) < before:
        save_config(config)
        logger.info(f"Removed keyword: {word}")
    else:
        logger.info(f"Keyword not found: {word}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    setup_logging(add_stream_handler=True)

    parser = argparse.ArgumentParser(
        description="BMW RSS Digest — fetch, filter, summarize"
    )
    parser.add_argument("--add-feed",       nargs=2, metavar=("URL", "NAME"))
    parser.add_argument("--add-keyword",    metavar="WORD")
    parser.add_argument("--remove-keyword", metavar="WORD")
    parser.add_argument("--list",           action="store_true")
    parser.add_argument("--from-date",      metavar="YYYY-MM-DD",
                        help="Filter items from this date")
    parser.add_argument("--to-date",        metavar="YYYY-MM-DD",
                        help="Filter items up to this date (default: now)")
    args = parser.parse_args()

    config = load_config()

    from_date: Optional[datetime] = None
    to_date:   Optional[datetime] = None

    if args.from_date:
        try:
            from_date = datetime.strptime(args.from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            logger.error(f"Invalid --from-date: {args.from_date}  (expected YYYY-MM-DD)")
            sys.exit(1)
    if args.to_date:
        try:
            to_date = datetime.strptime(args.to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            logger.error(f"Invalid --to-date: {args.to_date}  (expected YYYY-MM-DD)")
            sys.exit(1)

    if args.list:
        cmd_list(config)
    elif args.add_feed:
        cmd_add_feed(config, args.add_feed[0], args.add_feed[1])
    elif args.add_keyword:
        cmd_add_keyword(config, args.add_keyword)
    elif args.remove_keyword:
        cmd_remove_keyword(config, args.remove_keyword)
    else:
        run_digest(config, from_date=from_date, to_date=to_date)


if __name__ == "__main__":
    main()
