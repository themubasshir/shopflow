"""MedEx medicine-catalog ingestion (Phase 3A).

Collects the public MedEx brand catalogue (https://medex.com.bd/brands)
into a staging area, deduplicates it against the live ShopFlow catalog, and
lets a shop owner approve staged medicines into real ``products`` rows.

Authorization: the shop owner asserts written consent from MedEx for
scraping. Until the document's precise rate/scope limits are recorded, the
collector defaults to the most conservative posture — single-concurrency,
~1 request per 2 s, and an explicit page/detail cap — so a run cannot exceed
a reasonable authorization. Recurring collection is NOT enabled.
"""
