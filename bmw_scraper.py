#!/usr/bin/env python3
"""
BMW Forum Archive Scraper
Scrapes thread listings from bimmerpost-family forums (vBulletin),
filters by keywords, saves monthly Markdown files + full JSON index.

Usage:
  python3 bmw_scraper.py                        # scrape all feeds in config
  python3 bmw_scraper.py --feed "F30 DIY"       # scrape one feed by name
  python3 bmw_scraper.py --years 1              # override lookback period
  python3 bmw_scraper.py --dry-run              # show what would be scraped
  python3 bmw_scraper.py --stats                # show index stats
"""

import json
import sys
import os
import ssl
import re
import time
import argparse
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from html.parser import HTMLParser
from collections import defaultdict

# macOS SSL fix
ssl._create_default_https_context = ssl._create_unverified_context

# ── Config ────────────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent.resolve()
CONFIG_PATH  = SCRIPT_DIR / "bmw_rss_config.json"
INDEX_PATH   = SCRIPT_DIR / "bmw_archive_index.json"

LOOKBACK_YEARS  = 3
DELAY_SECONDS   = 1.5      # polite delay between page requests
MAX_PAGES       = 200      # safety cap per subforum

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def load_index():
    if INDEX_PATH.exists():
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}   # key: thread_id → thread dict

def save_index(index):
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

# ── URL helpers ───────────────────────────────────────────────────────────────

def extract_forum_id(rss_url):
    """Extract forumids=NNN from RSS URL."""
    m = re.search(r'forumids=(\d+)', rss_url)
    return m.group(1) if m else None

def extract_base_url(rss_url):
    """https://f30.bimmerpost.com/forums/external.php... → https://f30.bimmerpost.com/forums"""
    parsed = urllib.parse.urlparse(rss_url)
    return f"{parsed.scheme}://{parsed.netloc}/forums"

def make_forum_url(base_url, forum_id, page):
    return f"{base_url}/forumdisplay.php?f={forum_id}&order=desc&page={page}"

def make_thread_url(base_url, thread_id):
    return f"{base_url}/showthread.php?t={thread_id}"

# ── HTML Parser ───────────────────────────────────────────────────────────────

class ForumPageParser(HTMLParser):
    """
    Parse vBulletin forumdisplay page.
    Extracts thread rows: id, title, author, date string.
    """
    def __init__(self):
        super().__init__()
        self.threads   = []
        self._in_title = False
        self._current  = {}
        self._depth    = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        id_   = attrs.get("id", "")
        cls   = attrs.get("class", "")

        # Thread title link: <a href="showthread.php?t=NNN" id="thread_title_NNN">
        if tag == "a" and "thread_title_" in id_:
            tid = id_.replace("thread_title_", "")
            href = attrs.get("href", "")
            self._current = {"id": tid, "href": href, "title": "", "author": "", "date": ""}
            self._in_title = True

        # Last post date: <span class="time"> or inside td.lastpost
        if tag == "span" and "time" in cls and self._current.get("id"):
            pass  # handled via data

    def handle_endtag(self, tag):
        if tag == "a" and self._in_title:
            self._in_title = False
            if self._current.get("id"):
                self.threads.append(dict(self._current))

    def handle_data(self, data):
        if self._in_title:
            self._current["title"] += data.strip()


class ThreadMetaParser(HTMLParser):
    """
    Lighter pass: extract author and post date from thread listing row.
    We look for patterns in raw HTML instead.
    """
    pass


def parse_forum_page_raw(html):
    """
    Parse raw HTML from forumdisplay page (vBulletin 3.x).
    Returns list of dicts: {id, title, href, author, date_str}

    Structure observed:
      id="thread_title_NNN">TITLE</a>
      ...onclick="window.open('member.php?...', '_self')">AUTHOR</span>
      ...MM-DD-YYYY <span class="time">...
    """
    threads = []

    # split HTML into per-thread blocks using thread_title_ anchors
    positions = [(m.start(), m.group(1)) for m in
                 re.finditer(r'id="thread_title_(\d+)"', html)]

    if not positions:
        return threads

    # append sentinel
    positions.append((len(html), None))

    # date: MM-DD-YYYY
    date_re   = re.compile(r'(\d{2}-\d{2}-\d{4})', re.IGNORECASE)
    # title: text right after id="thread_title_NNN">
    title_re  = re.compile(r'id="thread_title_\d+"[^>]*>(.*?)</a>', re.DOTALL)
    # OP author: onclick="window.open('member.php?...', '_self')">NAME</span>
    author_re = re.compile(r"window\.open\('member\.php\?[^']*',\s*'_self'\)\">([^<]+)</span>")

    for i, (pos, tid) in enumerate(positions[:-1]):
        block = html[pos:positions[i+1][0]]

        # title
        tm = title_re.search(block)
        title = re.sub(r'<[^>]+>', '', tm.group(1)).strip() if tm else ""

        # last-post date (first date found in block)
        dm = date_re.search(block)
        date_str = dm.group(1) if dm else ""

        # OP author
        am = author_re.search(block)
        author = am.group(1).strip() if am else ""

        if title:
            threads.append({
                "id":       tid,
                "title":    title,
                "href":     f"showthread.php?t={tid}",
                "author":   author,
                "date_str": date_str,
            })

    return threads

# ── Date parsing ──────────────────────────────────────────────────────────────

DATE_FORMATS = [
    "%m-%d-%Y",   # vBulletin default: 03-11-2026
    "%Y-%m-%d",
    "%B %d, %Y",
    "%B %d %Y",
    "%b %d, %Y",
    "%b %d %Y",
]

def parse_date(date_str):
    if not date_str:
        return None
    ds = date_str.strip()
    if ds.lower() == "today":
        return datetime.now(timezone.utc)
    if ds.lower() == "yesterday":
        return datetime.now(timezone.utc) - timedelta(days=1)
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(ds, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None

# ── Keyword filter ────────────────────────────────────────────────────────────

def matches_keywords(title, keywords):
    t = title.lower()
    return any(kw.lower() in t for kw in keywords)

# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_page(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"    HTTP {e.code}: {url}")
        return None
    except Exception as e:
        print(f"    Error: {e}")
        return None

# ── Scrape one subforum ───────────────────────────────────────────────────────

def scrape_subforum(feed, keywords, cutoff_date, dry_run=False):
    """
    Scrape all pages of a subforum until threads are older than cutoff_date.
    Returns list of matched thread dicts.
    """
    rss_url   = feed["url"]
    name      = feed["name"]
    forum_id  = extract_forum_id(rss_url)
    base_url  = extract_base_url(rss_url)

    if not forum_id:
        print(f"  ⚠ Could not extract forum ID from: {rss_url}")
        return []

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Scraping: {name}  (forum {forum_id})")

    matched   = []
    seen_ids  = set()
    stop      = False

    for page in range(1, MAX_PAGES + 1):
        url = make_forum_url(base_url, forum_id, page)
        if dry_run:
            print(f"  Would fetch: {url}")
            break

        html = fetch_page(url)
        if not html:
            break

        threads = parse_forum_page_raw(html)
        if not threads:
            print(f"  Page {page}: no threads found, stopping")
            break

        new_this_page = 0
        old_this_page = 0

        for t in threads:
            if t["id"] in seen_ids:
                continue
            seen_ids.add(t["id"])

            dt = parse_date(t["date_str"])

            # stop condition
            if dt and dt < cutoff_date:
                old_this_page += 1
                continue

            new_this_page += 1

            full_url = make_thread_url(base_url, t["id"])
            thread = {
                "feed":     name,
                "id":       t["id"],
                "title":    t["title"],
                "url":      full_url,
                "author":   t["author"],
                "date":     dt.strftime("%Y-%m-%d") if dt else "",
                "date_str": t["date_str"],
                "keyword_match": matches_keywords(t["title"], keywords),
            }
            if thread["keyword_match"]:
                matched.append(thread)

        total_old = sum(1 for t in threads if parse_date(t.get("date_str")) and parse_date(t.get("date_str")) < cutoff_date)
        print(f"  Page {page}: {len(threads)} threads, "
              f"{new_this_page} recent, "
              f"{len([x for x in matched])} matched so far")

        # if most threads on this page are old, we're done
        if total_old > len(threads) * 0.7:
            print(f"  Most threads older than cutoff, stopping")
            break

        time.sleep(DELAY_SECONDS)

    return matched

# ── Output ────────────────────────────────────────────────────────────────────

def save_monthly_markdown(threads, output_dir):
    """Group threads by YYYY-MM and save one .md file per month."""
    output_dir = Path(output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    by_month = defaultdict(list)
    for t in threads:
        month = t["date"][:7] if t["date"] else "unknown"
        by_month[month].append(t)

    saved = []
    for month, items in sorted(by_month.items(), reverse=True):
        items.sort(key=lambda x: x["date"], reverse=True)
        filename = f"bmw_archive_{month}.md"
        path = output_dir / filename

        lines = [
            f"# BMW Archive — {month}",
            f"**Threads:** {len(items)}",
            "",
            "---",
            "",
        ]
        by_feed = defaultdict(list)
        for t in items:
            by_feed[t["feed"]].append(t)

        for feed_name, feed_items in sorted(by_feed.items()):
            lines.append(f"## {feed_name}")
            lines.append("")
            for t in feed_items:
                lines.append(f"### [{t['title']}]({t['url']})")
                meta = f"📅 {t['date']}"
                if t["author"]:
                    meta += f"  👤 {t['author']}"
                lines.append(meta)
                lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
        saved.append(path)

    return saved

def print_stats(index):
    if not index:
        print("Index is empty.")
        return
    total = len(index)
    by_feed = defaultdict(int)
    by_month = defaultdict(int)
    for t in index.values():
        by_feed[t["feed"]] += 1
        month = t["date"][:7] if t.get("date") else "unknown"
        by_month[month] += 1

    print(f"\n── Archive Index Stats ────────────────────────")
    print(f"  Total matched threads: {total}")
    print(f"\n  By subforum:")
    for feed, count in sorted(by_feed.items()):
        print(f"    {count:4d}  {feed}")
    print(f"\n  By month (last 12):")
    for month in sorted(by_month.keys(), reverse=True)[:12]:
        print(f"    {month}  {by_month[month]:4d} threads")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="BMW Forum Archive Scraper"
    )
    parser.add_argument("--feed",    metavar="NAME",
                        help="Scrape only feed matching this name (partial match)")
    parser.add_argument("--years",   type=float, default=LOOKBACK_YEARS,
                        help=f"Lookback period in years (default: {LOOKBACK_YEARS})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be scraped without fetching")
    parser.add_argument("--stats",   action="store_true",
                        help="Show index statistics")
    args = parser.parse_args()

    config     = load_config()
    index      = load_index()
    keywords   = config["keywords"]
    output_dir = Path(config["output_dir"]).expanduser() / "archive"
    cutoff     = datetime.now(timezone.utc) - timedelta(days=365 * args.years)

    if args.stats:
        print_stats(index)
        return

    feeds = config["feeds"]
    if args.feed:
        feeds = [f for f in feeds if args.feed.lower() in f["name"].lower()]
        if not feeds:
            print(f"No feed matching '{args.feed}'")
            return

    print(f"Lookback: {args.years} years (since {cutoff.strftime('%Y-%m-%d')})")
    print(f"Keywords: {', '.join(keywords)}")
    print(f"Feeds: {len(feeds)}")

    all_matched = []
    for feed in feeds:
        matched = scrape_subforum(feed, keywords, cutoff, dry_run=args.dry_run)
        all_matched.extend(matched)
        # merge into index (avoid duplicates)
        for t in matched:
            index[t["id"]] = t

    if not args.dry_run:
        save_index(index)
        print(f"\nIndex saved: {INDEX_PATH}  ({len(index)} total threads)")

        if all_matched:
            saved = save_monthly_markdown(all_matched, output_dir)
            print(f"Monthly files saved: {len(saved)}")
            for p in saved[:5]:
                print(f"  {p}")
            if len(saved) > 5:
                print(f"  ... and {len(saved)-5} more")
        else:
            print("No matched threads found.")

    print(f"\nDone. Total matched this run: {len(all_matched)}")

if __name__ == "__main__":
    main()
