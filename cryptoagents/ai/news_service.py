"""金融/加密新闻实时抓取 — 使用免费 RSS 源 (CoinDesk / CoinTelegraph, 无需密钥)。

带内存缓存避免频繁请求。
"""
from __future__ import annotations

import re
import time
from typing import Any
from xml.etree import ElementTree

from app.core.logging_config import get_logger

logger = get_logger("news_service")

_cache: dict[str, Any] = {"data": [], "ts": 0}
_CACHE_TTL = 120  # 秒

_SOURCES = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("CoinTelegraph", "https://cointelegraph.com/rss"),
]


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"&[a-z]+;", " ", text)
    return text.strip()


def _parse_rss(source_name: str, xml_text: str) -> list[dict[str, Any]]:
    out = []
    try:
        root = ElementTree.fromstring(xml_text)
        for item in root.iter("item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            desc = _strip_html(item.findtext("description", ""))
            pub = item.findtext("pubDate", "")
            ts = 0
            try:
                from email.utils import parsedate_to_datetime
                ts = int(parsedate_to_datetime(pub).timestamp())
            except Exception:
                ts = int(time.time())
            out.append({
                "title": title.strip(),
                "body": desc[:400],
                "source": source_name,
                "url": link.strip(),
                "published_at": ts,
                "categories": "", "tags": "", "image": "",
            })
    except Exception as exc:
        logger.warning(f"{source_name} RSS解析失败: {exc}")
    return out


def fetch_news(categories: str = "", limit: int = 20, force: bool = False) -> list[dict[str, Any]]:
    now = time.time()
    if not force and _cache["data"] and (now - _cache["ts"] < _CACHE_TTL):
        return _cache["data"][:limit]
    items: list[dict[str, Any]] = []
    try:
        import httpx
        with httpx.Client(timeout=15, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0"}) as c:
            for name, url in _SOURCES:
                try:
                    r = c.get(url)
                    if r.status_code == 200:
                        items.extend(_parse_rss(name, r.text))
                except Exception as exc:
                    logger.warning(f"{name} 抓取失败: {exc}")
    except Exception as exc:
        logger.warning(f"新闻抓取失败: {exc}")

    if items:
        items.sort(key=lambda x: x["published_at"], reverse=True)
        _cache["data"] = items
        _cache["ts"] = now
    return (_cache["data"] or items)[:limit]


def news_digest(limit: int = 10) -> str:
    items = fetch_news(limit=limit)
    if not items:
        return "（暂无新闻数据）"
    return "\n".join(f"{i}. [{n['source']}] {n['title']}" for i, n in enumerate(items, 1))
