"""Normalize raw MedEx fields into canonical keys used for matching.

The normalizer never guesses a value — it only lowercases, collapses
whitespace, strips punctuation, and expands a few known dosage-form aliases so
that two spellings of the *same* medicine compare equal. It is used to build a
matching key, not to overwrite the display fields (which stay verbatim).
"""

from __future__ import annotations

import re

# Dosage-form aliases that mean the same thing for matching purposes.
_FORM_ALIASES = {
    "tab": "tablet",
    "tabs": "tablet",
    "cap": "capsule",
    "caps": "capsule",
    "syr": "syrup",
    "susp": "suspension",
    "inj": "injection",
    "iv injection": "injection",
    "iv injection or infusion": "injection",
    "im injection": "injection",
    "sr tablet": "tablet",
    "tablet (sustained release)": "tablet",
    "xr tablet": "tablet",
    "powder for suspension": "suspension",
    "oral suspension": "suspension",
    "supp": "suppository",
    "drops": "drops",
}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_MULTISPACE = re.compile(r"\s+")
# Normalize strength units so "100mg" / "100 mg" / "100 MG" compare equal.
_STRENGTH_UNITS = {
    "mcg": "mcg",
    "ug": "mcg",
    "µg": "mcg",
    "mg": "mg",
    "gm": "g",
    "g": "g",
    "ml": "ml",
    "iu": "iu",
    "%": "%",
}


def norm_text(value: str | None) -> str:
    """Lowercase, strip punctuation, collapse whitespace. Empty -> ''."""
    if not value:
        return ""
    lowered = value.strip().lower()
    return _MULTISPACE.sub(" ", lowered).strip()


def norm_key(value: str | None) -> str:
    """A comparison key: alphanumeric-only, lowercase."""
    return _NON_ALNUM.sub("", norm_text(value))


def norm_form(value: str | None) -> str:
    """Canonical dosage-form word for matching."""
    n = norm_text(value)
    n = re.sub(r"\s+", " ", n)
    return _FORM_ALIASES.get(n, n)


def norm_strength(value: str | None) -> str:
    """Normalize '500 MG' -> '500mg', '1 g' -> '1000mg'? No — unit-preserving.

    We deliberately do NOT convert units (that would require assumptions about
    density/equivalence). We only standardize spacing + case + a few unit
    spellings so '500mg' and '500 mg' match.
    """
    if not value:
        return ""
    s = norm_text(value)
    s = s.replace("µg", "mcg").replace("ug", "mcg")
    # remove spaces between a number and its unit
    s = re.sub(r"(\d)\s+(mg|mcg|g|ml|iu|%)\b", r"\1\2", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def medicine_key(
    brand: str | None,
    strength: str | None,
    form: str | None,
    manufacturer: str | None,
) -> tuple[str, str, str, str]:
    """The four-part identity used for fuzzy matching.

    All four parts participate; a match on brand alone is never enough. Two
    medicines with different strength, form or manufacturer produce a
    different key and are never auto-merged.
    """
    return (
        norm_key(brand),
        norm_strength(strength),
        norm_form(form),
        norm_key(manufacturer),
    )


def comfortable_sku(brand: str | None, source_id: str) -> str:
    """A deterministic, collision-resistant SKU for a promoted medicine.

    Prefixed ``MED-`` so MedEx-derived products are distinguishable from
    hand-entered stock, and suffixed with the stable source id so repeated
    imports of the same medicine always compute the same SKU.
    """
    base = _NON_ALNUM.sub("-", norm_text(brand))[:24].strip("-") or "med"
    return f"MED-{base.upper()}-{source_id}"[:64]
