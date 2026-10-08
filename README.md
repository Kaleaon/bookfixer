# Takeout Book Fixer for Calibre

Install `dist/TakeoutBookFixer.zip` in Calibre 6 or newer using **Preferences → Plugins → Load plugin from file**, then restart Calibre. Add **Takeout Book Fixer** to the toolbar through **Preferences → Toolbars & menus** if needed.

Choose an individual book file, Google Takeout folder, or ZIP through the plugin menu, then select a separate output folder. Automatic import into the current Calibre library is enabled by default and can be unchecked. Originals remain untouched. Each run writes a JSON report listing recovered, skipped, and failed files. Content hashes keep output names distinct and avoid duplicate copies on repeated runs.

The plugin detects PDF, EPUB, MOBI, DjVu and ZIP comic containers from content rather than extensions. Existing `.cbr` files with RAR signatures are copied; other RAR files are skipped because a RAR signature alone cannot establish that the archive contains a comic. Unsupported files and metadata are skipped. DRM is not removed. EPUB recognition requires its standard mimetype and container entries; recognition does not validate the entire book.

Optional PDF conversion renders every page of a PDF with no detected word characters to an ordered CBZ. It preserves page appearance, including drawing and overlays, rather than pulling out embedded images that may omit page elements. It skips text-bearing PDFs. Scanned novels also qualify: enable this option only when you want such PDFs treated as comics. PDFs cannot become EPUBs by renaming; only actual EPUB containers mislabeled as PDF receive `.epub`.

PDF conversion requires **PyMuPDF** available to Calibre's Python runtime, or **Poppler** (`pdfinfo`, `pdftotext`, `pdftoppm`) on Calibre's PATH. Installing PyMuPDF in an unrelated system Python may not make it available to Calibre. Format recovery works without either. Conversion renders at approximately 144 DPI with PyMuPDF or a 2400-pixel maximum side with Poppler. Encrypted PDFs are not converted. Large batches may take time. Safety limits: 512 MiB per input/output file, 10 GiB input batch, 2000 PDF pages. The ZIP is read without extracting archive paths.

Build: `python build.py`. Test: `python -m unittest discover -s tests -v` (PDF tests require PyMuPDF). Verified with Calibre 9.15 on Linux: plugin installation, Qt menu creation, complete recovery/import action with automated dialogs, actual library format storage, embedded metadata and cover extraction, matching JSON sidecar metadata, duplicate skipping, and CBZ library import. PDF conversion and text protection also passed inside Calibre’s runtime using Poppler. Interactive file selection and other operating systems have not been tested.

The importer reads embedded book metadata and covers using Calibre. Matching JSON sidecars (`book.pdf.json` or `book.json` beside `book.pdf`) supplement title, authors, publisher, description, language, categories, publication date and ISBN, including Google Books `volumeInfo` objects. Missing titles fall back to the original filename. Unsupported sidecar layouts are not guessed. No online metadata lookup is performed. Identical formats with the same title are skipped on subsequent imports. The JSON report includes import results and Calibre book IDs.

The plugin menu also includes **Repair selected books already in Calibre**. Select books in the library, choose that command, and it checks every stored format by signature. A mislabeled EPUB is saved as EPUB and the old format is removed only after the corrected format is safely stored. The optional PDF-to-CBZ conversion is available here too. Metadata is refreshed from the corrected file when Calibre can read it. Books with unknown content are left unchanged.

## Real Takeout validation

Version 1.0.1 was tested with the shared January 2025 export part 003: all 51 books recovered and imported into Calibre 9.15 with no errors. Content inspection identified 47 EPUBs and four PDFs; 16 of those EPUBs had been named `.pdf`. Calibre recovered known authors for 48 books and covers for all 51. Takeout ZIPs are streamed per member, allowing the archive itself to exceed the individual-book size limit. Other parts of the export and the full October 2026 export were not validated.

Optional comic conversion was also verified with both real image-only PDFs (45 pages each): all pages rendered and both CBZs imported successfully. Both text-bearing PDFs stayed PDF. Lossless rendering took several minutes per comic in this environment.

# EPUB Promo Scrubber for Calibre

Install `dist/EpubPromoScrubber.zip` the same way (Preferences → Plugins → Load plugin from file), restart, and add **EPUB Promo Scrubber** to a toolbar if needed. It removes marks that sites add on top of a book: "Downloaded from …" banner pages and lines, hyperlinks to those sites, and site names in the book's metadata. Built-in names are OceanofPDF, PDFDrive, Z-Library, LibGen and Library Genesis. **Settings…** lets you add more site names, domains or `re:` regular expressions, and toggle the options below.

- **Scrub selected books in Calibre** rewrites each selected book's EPUB and also cleans the library's title, publisher and comments fields. The unmodified EPUB is kept as ORIGINAL_EPUB unless you turn that off.
- **Scrub EPUB file or folder** writes cleaned copies and a `scrub-report.json` to a separate folder; originals are untouched.

What it does inside the EPUB: deletes short blocks (250 characters or fewer) that name a blocked site; unwraps or removes links to it; trims leftover mentions in longer paragraphs; deletes pages that end up empty, along with their spine, contents and guide entries; cleans Dublin Core metadata and the ZIP comment. Optionally, short "Downloaded from <any website>" / "free ebooks" blocks from unlisted sites are removed too. Links to an author's or publisher's own site are kept. Every change is listed in the report.

Limits: watermarks baked into images or cover art are not detected. XHTML files that are not well-formed XML (including older files relying on `&nbsp;`-style DTD entities, and encrypted files) are left unchanged and flagged in the report. DRM is not touched. The text-matching rules can remove legitimate short passages that mention a blocked name, which is why the original is kept by default and each removal is reported.

Testing: the cleaning logic has unit tests (`python -m unittest tests.test_scrubber`) run against synthetic EPUBs. The Calibre GUI wrapper (`scrubber_plugin/action.py`) has **not** been run inside Calibre, and no real-world EPUBs have been tried.
