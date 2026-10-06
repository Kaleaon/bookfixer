# Takeout Book Fixer 1.0.1 validation

Calibre 9.15 on Linux, using the shared `takeout-20250107T221758Z-003.zip`.

- 51/51 books recovered and imported; zero import errors.
- Detected 47 EPUBs and 4 genuine PDFs.
- Corrected 16 `.pdf` files that actually contained EPUBs.
- Author metadata available for 48 books; covers for all 51.
- Checked each new Calibre entry for a stored format and title.
- Separate synthetic checks verified JSON sidecar metadata, embedded metadata and covers, duplicate detection, GUI action execution with automated dialogs, and CBZ import.
- Six core regression tests passed.
- Large Takeout archives are read per member instead of loading the entire archive into memory.

The January export part 003 was tested; other export parts and the complete October 2026 export were not validated. Originals were not modified.

Real PDF checks also passed: both text-bearing PDFs remained PDF; both image-only PDFs rendered all 45 pages to CBZ and imported into a separate Calibre library.
