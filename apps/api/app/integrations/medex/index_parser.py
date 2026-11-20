"""Parse MedEx ``/brands`` index pages into ``IndexCard`` records.

The page is a grid of ``<a class="brand-card" href="/brands/{id}/{slug}">``
anchors. Each card exposes a brand name, a strength line, a generic name, a
company name, and a dosage-form icon whose ``title`` attribute names the
form. Pagination is Laravel-style ``?page=N`` with ``rel="next"`` and a
trailing highest-numbered link — discovered, never assumed.

The parser reads the *current live markup*; it does not hard-code any page
count. When the structure drifts it returns empty/warned results rather than
fabricating cards.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.integrations.medex.schemas import IndexCard, IndexPage

_BASE = "https://medex.com.bd"

# /brands/13717/3-bion-100-mg-tablet  ->  ("13717", "3-bion-100-mg-tablet")
_BRAND_URL = re.compile(r"^/brands/(\d+)/([A-Za-z0-9\-_]+)/?$")


def _canonical_detail_url(href: str) -> tuple[str, str, str] | None:
    """Return (source_id, slug, canonical_url) or None if not a detail link.

    Strips ``/bn`` language suffixes and query strings so the same medicine
    always resolves to one canonical URL.
    """
    parsed = urlparse(urljoin(_BASE, href))
    path = parsed.path.rstrip("/")
    if path.endswith("/bn"):
        path = path[: -len("/bn")]
    m = _BRAND_URL.match(path)
    if not m:
        return None
    source_id, slug = m.group(1), m.group(2)
    return source_id, slug, f"{_BASE}/brands/{source_id}/{slug}"


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    t = " ".join(text.split())
    return t or None


def _text(node) -> str | None:
    if node is None:
        return None
    return _clean(node.get_text(" ", strip=True))


def _page_number_from_url(url: str) -> int | None:
    m = re.search(r"[?&]page=(\d+)", url)
    return int(m.group(1)) if m else (1 if url.rstrip("/").endswith("brands") else None)


def parse_index(html: str, source_url: str = f"{_BASE}/brands") -> IndexPage:
    """Parse one index page. ``source_url`` is the page that produced ``html``
    (used to stamp the current page number)."""
    soup = BeautifulSoup(html, "lxml")
    cards: list[IndexCard] = []
    seen: set[str] = set()

    for a in soup.select("a.brand-card[href]"):
        resolved = _canonical_detail_url(a["href"])
        if resolved is None:
            continue
        source_id, slug, url = resolved
        if source_id in seen:  # duplicate link on the same page
            continue
        seen.add(source_id)

        icon = a.select_one(".dosage-icon")
        dosage = None
        if icon is not None:
            dosage = _clean(icon.get("title")) or _clean(icon.get("alt"))
        cards.append(
            IndexCard(
                source_id=source_id,
                slug=slug,
                url=url,
                brand_name=_text(a.select_one(".brand-card__name")) or "",
                strength=_text(a.select_one(".brand-card__strength")),
                generic_name=_text(a.select_one(".brand-card__generic")),
                manufacturer=_text(a.select_one(".brand-card__company")),
                dosage_form=dosage,
            )
        )

    # Pagination: collect every ?page=N we can see + the rel="next" link.
    last_page: int | None = None
    next_url: str | None = None
    for a in soup.select("ul.pagination a.page-link[href], nav a.page-link[href]"):
        href = a.get("href", "")
        m = re.search(r"[?&]page=(\d+)", href)
        if m:
            last_page = max(last_page or 0, int(m.group(1)))
        if a.get("rel") == "next" or "next" in (a.get("aria-label") or "").lower():
            next_url = urljoin(_BASE, href)

    return IndexPage(
        cards=cards,
        page_number=_page_number_from_url(source_url),
        last_page=last_page,
        next_page_url=next_url,
    )


def detail_id_from_url(url: str) -> str | None:
    """Extract the numeric MedEx id from any brand detail URL (incl. /bn)."""
    path = urlparse(urljoin(_BASE, url)).path.rstrip("/")
    if path.endswith("/bn"):
        path = path[: -len("/bn")]
    m = _BRAND_URL.match(path)
    return m.group(1) if m else None
