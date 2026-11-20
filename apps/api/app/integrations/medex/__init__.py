"""MedEx medicine-catalog ingestion (Phase 3A / 3E).

Offline import of the MedEx-derived medicine dataset into the staging area,
then promotion into live ``products`` rows. The live web scraper was removed —
the catalog is now populated from a CSV already on disk
(``Mahadih534/all-Bangladeshi-medicines``, CC-BY-2.0) through
``dataset_importer``; the staging→approve→promote pipeline is unchanged.
"""
