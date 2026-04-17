from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

USER_AGENT = "TopJournalBriefing/0.3 (mailto:research@example.com)"
HEADERS = {"User-Agent": USER_AGENT}
TIMEOUT = 20


def load_journal_config(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["journals"]


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(" ", strip=True)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def extract_doi(text: str) -> Optional[str]:
    if not text:
        return None
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, re.I)
    return match.group(0).rstrip(').,;]') if match else None


def get_entry_abstract(entry: Any) -> str:
    candidates = []
    for field in ["summary", "description", "subtitle"]:
        value = getattr(entry, field, None) or entry.get(field)
        if value:
            candidates.append(value)
    if entry.get("content"):
        for item in entry["content"]:
            if item.get("value"):
                candidates.append(item["value"])
    for candidate in candidates:
        clean = normalize_whitespace(strip_html(candidate))
        if len(clean) > 80:
            return clean
    return ""


def _parse_any_date(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = dateparser.parse(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def parse_entry_date(entry: Any) -> Optional[datetime]:
    # feedparser often exposes *_parsed even when string dates are absent
    for parsed_field in ["published_parsed", "updated_parsed", "created_parsed"]:
        value = getattr(entry, parsed_field, None) or entry.get(parsed_field)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    for field in ["published", "updated", "created"]:
        value = getattr(entry, field, None) or entry.get(field)
        dt = _parse_any_date(value)
        if dt:
            return dt
    return None


def _date_from_crossref_parts(msg: Dict[str, Any], key: str) -> Optional[datetime]:
    parts = msg.get(key, {}).get("date-parts")
    if not parts or not parts[0]:
        return None
    vals = list(parts[0])
    while len(vals) < 3:
        vals.append(1)
    try:
        return datetime(vals[0], vals[1], vals[2], tzinfo=timezone.utc)
    except Exception:
        return None


def crossref_enrich(doi: str) -> Dict[str, Any]:
    url = f"https://api.crossref.org/works/{quote_plus(doi)}"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    msg = r.json().get("message", {})
    abstract = normalize_whitespace(strip_html(msg.get("abstract", "")))
    subjects = msg.get("subject", []) or []
    article_type = msg.get("type", "")
    container = (msg.get("container-title") or [""])[0]
    link = ""
    if msg.get("URL"):
        link = msg["URL"]
    return {
        "title": normalize_whitespace(strip_html((msg.get("title") or [""])[0])),
        "abstract": abstract,
        "subjects": subjects,
        "article_type": article_type,
        "container_title": container,
        "link": link,
        "published_online": _date_from_crossref_parts(msg, "published-online"),
        "published_print": _date_from_crossref_parts(msg, "published-print"),
        "created_date": _date_from_crossref_parts(msg, "created"),
    }


def fetch_feed_entries(feed_url: str) -> List[Any]:
    r = requests.get(feed_url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    parsed = feedparser.parse(r.content)
    return parsed.entries or []


def choose_best_date(
    published_online: Optional[datetime],
    published_print: Optional[datetime],
    rss_date: Optional[datetime],
    created_date: Optional[datetime],
) -> tuple[Optional[datetime], str]:
    if published_online:
        return published_online, "Crossref published-online"
    if published_print:
        return published_print, "Crossref published-print"
    if rss_date:
        return rss_date, "RSS published/updated"
    if created_date:
        return created_date, "Crossref created"
    return None, "Unknown"


def _norm_title(s: str) -> str:
    return normalize_whitespace((s or "").lower())


def _crossref_recent_for_journal(journal: Dict[str, Any], days_back: int) -> List[Dict[str, Any]]:
    start_date = (datetime.now(timezone.utc) - timedelta(days=days_back + 2)).strftime("%Y-%m-%d")
    # Crossref allows date filters; we then post-filter to the exact journal title.
    url = (
        "https://api.crossref.org/works?rows=25&sort=published&order=desc"
        f"&filter=from-pub-date:{start_date}"
        f"&query.container-title={quote_plus(journal['journal'])}"
        "&select=DOI,title,container-title,URL,abstract,subject,type,published-online,published-print,created"
    )
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    items = r.json().get("message", {}).get("items", [])
    out = []
    for msg in items:
        container = normalize_whitespace(((msg.get("container-title") or [""])[0]))
        if _norm_title(container) != _norm_title(journal["journal"]):
            continue
        doi = msg.get("DOI", "")
        title = normalize_whitespace(strip_html(((msg.get("title") or [""])[0])) )
        abstract = normalize_whitespace(strip_html(msg.get("abstract", "")))
        published_online = _date_from_crossref_parts(msg, "published-online")
        published_print = _date_from_crossref_parts(msg, "published-print")
        created_date = _date_from_crossref_parts(msg, "created")
        best_date, date_source = choose_best_date(published_online, published_print, None, created_date)
        out.append(
            {
                "family": journal["family"],
                "journal": journal["journal"],
                "homepage": journal["homepage"],
                "title": title,
                "link": msg.get("URL", ""),
                "doi": doi,
                "checked_at": datetime.now(timezone.utc),
                "rss_date": None,
                "published_online": published_online,
                "published_print": published_print,
                "created_date": created_date,
                "best_date": best_date,
                "date_source": date_source + " (fallback)",
                "abstract": abstract,
                "article_type": msg.get("type", ""),
                "subjects": msg.get("subject", []) or [],
                "source_mode": "crossref_fallback",
            }
        )
    return out


def fetch_articles(journals: List[Dict[str, Any]], days_back: int = 7) -> List[Dict[str, Any]]:
    articles: List[Dict[str, Any]] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    checked_at = datetime.now(timezone.utc)
    journal_status: List[Dict[str, Any]] = []

    for journal in journals:
        recovered_for_journal: List[Dict[str, Any]] = []
        feed_ok = False
        feed_error = ""
        try:
            entries = fetch_feed_entries(journal["feed_url"])
            feed_ok = True
        except Exception as e:
            entries = []
            feed_error = str(e)

        for entry in entries:
            title = normalize_whitespace(strip_html(entry.get("title", "")))
            link = entry.get("link", "")
            rss_date = parse_entry_date(entry)
            doi = (
                extract_doi(link)
                or extract_doi(entry.get("id", ""))
                or extract_doi(entry.get("summary", ""))
                or extract_doi(title)
            )
            abstract = get_entry_abstract(entry)
            subjects: List[str] = []
            article_type = ""
            published_online = None
            published_print = None
            created_date = None

            if doi:
                try:
                    enriched = crossref_enrich(doi)
                    if not title and enriched.get("title"):
                        title = enriched["title"]
                    if not abstract and enriched.get("abstract"):
                        abstract = enriched["abstract"]
                    subjects = enriched.get("subjects", [])
                    article_type = enriched.get("article_type", "")
                    published_online = enriched.get("published_online")
                    published_print = enriched.get("published_print")
                    created_date = enriched.get("created_date")
                    if not link and enriched.get("link"):
                        link = enriched["link"]
                except Exception:
                    pass

            best_date, date_source = choose_best_date(
                published_online=published_online,
                published_print=published_print,
                rss_date=rss_date,
                created_date=created_date,
            )
            if best_date and best_date < cutoff:
                continue

            recovered_for_journal.append(
                {
                    "family": journal["family"],
                    "journal": journal["journal"],
                    "homepage": journal["homepage"],
                    "title": title,
                    "link": link,
                    "doi": doi or "",
                    "checked_at": checked_at,
                    "rss_date": rss_date,
                    "published_online": published_online,
                    "published_print": published_print,
                    "created_date": created_date,
                    "best_date": best_date,
                    "date_source": date_source,
                    "abstract": abstract,
                    "article_type": article_type,
                    "subjects": subjects,
                    "source_mode": "rss",
                }
            )

        if not recovered_for_journal:
            try:
                recovered_for_journal = _crossref_recent_for_journal(journal, days_back)
            except Exception as e:
                if not feed_error:
                    feed_error = f"Crossref fallback failed: {e}"

        articles.extend(recovered_for_journal)
        journal_status.append(
            {
                "family": journal["family"],
                "journal": journal["journal"],
                "feed_ok": feed_ok,
                "recovered_count": len(recovered_for_journal),
                "source_mode": recovered_for_journal[0]["source_mode"] if recovered_for_journal else "none",
                "feed_error": feed_error,
            }
        )

    deduped: Dict[str, Dict[str, Any]] = {}
    for art in articles:
        key = art["doi"] or art["link"] or art["title"]
        current = deduped.get(key)
        if current is None:
            deduped[key] = art
            continue
        current_date = current.get("best_date") or datetime(1970, 1, 1, tzinfo=timezone.utc)
        new_date = art.get("best_date") or datetime(1970, 1, 1, tzinfo=timezone.utc)
        if new_date > current_date:
            deduped[key] = art

    result = list(deduped.values())
    result.sort(key=lambda x: x["best_date"] or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    return {"articles": result, "journal_status": journal_status}
