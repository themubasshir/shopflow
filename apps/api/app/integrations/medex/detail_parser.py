"""Parse a MedEx ``/brands/{id}/{slug}`` detail page into ``MedicineDetail``.

Reads both the English page and (when fetched) the ``/bn`` variant. The two
layouts differ: the Bangla page wraps the brand name in ``span.tx-0-95`` and
localises strength / generic / manufacturer / dosage form. Prices stay in
Latin digits on both variants.

Price block shapes seen in the wild:

* ``Unit Price: ৳ 0.86 (10 x 10: ৳ 86.00)`` + ``Strip Price: ৳ 8.60``
* a custom label like ``90 ml bottle: ৳ 1,375.00`` (no literal "Unit Price")
* several ``package-container`` blocks (e.g. different pack presentations)
* no price block at all -> all price fields stay ``None``.

``prescription_note`` is only populated from an *explicit* on-page
designation — it is never inferred from the generic name.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.integrations.medex.index_parser import detail_id_from_url
from app.integrations.medex.schemas import MedicineDetail, PackInfo

_MONEY = re.compile(r"৳\s*([0-9,]+(?:\.\d+)?)")
# "(10 x 10: ৳ 86.00)" or "(1 x 5's: ৳ 12.50)"
# Source pages render pack info with the multiplication sign and fullwidth
# colon literally; matching them requires those characters in the pattern.
_PACK = re.compile(
    r"\((\d+)\s*[x×]\s*(\d+)(?:'\s*s)?\s*[:：]\s*৳?\s*([0-9,]+(?:\.\d+)?)\)",  # noqa: RUF001
    re.I,
)
_BENGALI_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    t = " ".join(text.split())
    return t or None


def _money(text: str | None) -> float | None:
    if not text:
        return None
    m = _MONEY.search(text)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def _to_decimal(value: float | None):
    if value is None:
        return None
    from decimal import Decimal

    return Decimal(str(round(value, 2)))


def _by_title(soup: BeautifulSoup, *titles: str):
    """First ``div[title=...]`` whose text is non-empty (tries each title)."""
    for title in titles:
        node = soup.find("div", attrs={"title": title})
        if node:
            txt = _clean(node.get_text(" ", strip=True))
            if txt:
                return node, txt
    return None, None


def _is_bangla(soup: BeautifulSoup) -> bool:
    block = soup.find(id="ms-block")
    return bool(block and "lang-bn" in (block.get("class") or []))


def parse_detail(html: str, url: str, *, content: bytes | None = None) -> MedicineDetail:
    """Parse one detail page (English or Bangla). ``url`` is the canonical
    English URL the record is keyed under; ``content`` lets the caller pass the
    raw bytes so the content hash matches what was fetched."""
    soup = BeautifulSoup(html, "lxml")
    bangla = _is_bangla(soup)
    detail = MedicineDetail(
        source_id=detail_id_from_url(url) or "",
        url=url.split("?")[0].removesuffix("/bn"),
        slug=(urlparse(url).path.rstrip("/").split("/")[-1] or None),
    )
    detail.content_hash = hashlib.sha256(
        content if content is not None else html.encode("utf-8")
    ).hexdigest()

    # --- Brand name + dosage form -------------------------------------------
    h1 = soup.select_one("h1.brand") or soup.select_one("h1.page-heading-1-l")
    if h1:
        if bangla:
            # Bangla layout: <span class="tx-0-95">NAME <small>FORM</small></span>
            span = h1.find("span", class_="tx-0-95") or h1.find("span")
            name_text = span.get_text(" ", strip=True) if span else h1.get_text(" ", strip=True)
            form_txt = None
            for sub in h1.find_all("small", class_="h1-subtitle"):
                st = _clean(sub.get_text(" ", strip=True))
                if st:
                    form_txt = form_txt or st
                    name_text = name_text.replace(st, "")
            detail.brand_name_bn = _clean(name_text)
            detail.dosage_form_bn = form_txt
        else:
            # English: brand name is the h1 text; each <small class="h1-subtitle">
            # is a dosage-form variant (desktop/mobile can differ). Strip them all.
            subs = h1.find_all("small", class_="h1-subtitle")
            name_text = h1.get_text(" ", strip=True)
            form_txt: str | None = None
            for sub in subs:
                st = _clean(sub.get_text(" ", strip=True))
                if st:
                    form_txt = form_txt or st
                    name_text = name_text.replace(st, "")
            detail.brand_name = _clean(name_text)
            detail.dosage_form = form_txt
        # fallback dosage form from the header icon title
        icon = soup.select_one(".brand-th-block .dosage-icon, h1 .dosage-icon")
        if icon and (icon.get("title") or icon.get("alt")):
            if bangla and not detail.dosage_form_bn:
                detail.dosage_form_bn = icon.get("title") or icon.get("alt")
            elif not bangla and not detail.dosage_form:
                detail.dosage_form = icon.get("title") or icon.get("alt")

    # --- Generic / strength / manufacturer ----------------------------------
    gen_node, gen_txt = _by_title(soup, "Generic Name")
    if gen_node:
        link = gen_node.find("a")
        val = _clean(link.get_text(" ", strip=True)) if link else gen_txt
        if bangla:
            detail.generic_name_bn = val
        else:
            detail.generic_name = val

    _, strength = _by_title(soup, "Strength")
    if strength:
        if bangla:
            detail.strength_bn = strength
            # keep a Latin-digit copy too for downstream numeric parsing
            detail.strength = detail.strength or _clean(strength.translate(_BENGALI_DIGITS))
        else:
            detail.strength = strength

    # Prefer the marketer when present; a nested "(Mfg. by: …)" note is kept
    # out of the primary manufacturer field.
    mfr_node, _ = _by_title(soup, "Marketed by", "Manufactured by")
    if mfr_node:
        link = mfr_node.find("a")
        mfr = (
            _clean(link.get_text(" ", strip=True))
            if link
            else _clean(mfr_node.get_text(" ", strip=True))
        )
        if bangla:
            detail.manufacturer_bn = mfr
        else:
            detail.manufacturer = mfr

    # --- Prices --------------------------------------------------------------
    for pkg in soup.select("div.package-container"):
        pkg_text = " ".join(pkg.get_text(" ", strip=True).split())
        label_m = re.match(r"^([^:：]{1,40})[:：]", pkg_text)  # noqa: RUF001
        label = _clean(label_m.group(1)) if label_m else None
        price = _to_decimal(_money(pkg_text))

        pack = PackInfo(label=label, price=price, raw=pkg_text)
        pm = _PACK.search(pkg_text)
        if pm:
            pack.pack_quantity = int(pm.group(1))
            pack.units_per_pack = int(pm.group(2))
            pack.pack_price = _to_decimal(float(pm.group(3).replace(",", "")))
            detail.pack = pack
            # treat the labelled price as the unit price when labelled so
            if (label and "unit" in label.lower()) or detail.unit_price is None:
                detail.unit_price = price
        else:
            # No "(N x M: ৳)" -> a simple labelled price ("Unit Price:" or
            # a pack descriptor like "90 ml bottle").
            if label and "unit" in label.lower():
                detail.unit_price = price
            elif label and "strip" in label.lower():
                detail.strip_price = price
            elif detail.unit_price is None and label is None:
                detail.unit_price = price
            elif detail.pack is None:
                detail.pack = pack
        prior = detail.raw_price_text or ""
        detail.raw_price_text = (prior + " | " if prior else "") + pkg_text

        # explicit "Strip Price:" sub-line — take the amount AFTER that label,
        # not the container's first (which is the unit price).
        strip_m = re.search(
            r"strip price\s*[:：]\s*৳\s*([0-9,]+(?:\.\d+)?)",  # noqa: RUF001
            pkg_text,
            re.I,
        )
        if strip_m and detail.strip_price is None:
            detail.strip_price = _to_decimal(float(strip_m.group(1).replace(",", "")))

    # --- Therapeutic class ----------------------------------------------------
    ther = soup.find(id="drug_classes")
    if ther:
        body = ther.find_next_sibling("div", class_="ac-body") or ther.find_next(
            "div", class_="ac-body"
        )
        if body:
            detail.therapeutic_class = _clean(body.get_text(" ", strip=True))

    # --- Explicit prescription designation -----------------------------------
    # Only honour an explicit on-page statement; never infer.
    for marker in soup.find_all(
        string=re.compile(r"prescription only|rx only|prescription required", re.I)
    ):
        detail.prescription_note = _clean(marker)
        break

    # --- Warnings --------------------------------------------------------------
    if not detail.brand_name and not detail.brand_name_bn:
        detail.parse_warnings.append("missing_brand_name")
    if not detail.generic_name and not detail.generic_name_bn:
        detail.parse_warnings.append("missing_generic_name")
    if detail.unit_price is None and detail.strip_price is None and detail.pack is None:
        detail.parse_warnings.append("no_price_block")
    if not detail.source_id:
        detail.parse_warnings.append("missing_source_id")

    return detail
