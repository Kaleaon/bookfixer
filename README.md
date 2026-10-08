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

# Story downloaders and tagger for Calibre

Four more plugins live beside the Takeout fixer. Build all zips with `python build_plugins.py` (output in `dist/`; the fanfic zip needs `pip install fanficfare` in the Python that runs the script, otherwise it is skipped with a message, and `--strict` makes that an error); install each through **Preferences → Plugins → Load plugin from file**, restart Calibre, and add its button via **Preferences → Toolbars & menus** if needed. Calibre 6 or newer. Shared code (`common/`: fetching, text cleaning, EPUB building, library import) is bundled into each downloader's zip.

| Plugin | Zip | Purpose |
| --- | --- | --- |
| Metabods Downloader | `MetabodsDownloader.zip` | Metabods stories → EPUB, tag search, favorites |
| Nifty Downloader | `NiftyDownloader.zip` | Nifty archive stories → EPUB, category browser |
| Story Collection Tagger | `StoryCollectionTagger.zip` | Tag books by source site and your own keyword rules |
| Fanfic Site Downloader | `FanficDownloader.zip` | Royal Road, AO3 and 100+ other sites via FanFicFare's adapters, with an adult-sites setting |

Stories are copyrighted by their authors and both sites ask that they not be reposted, so these are for personal reading copies. Requests are throttled to about one per second and run in a background thread with a Cancel button; whatever was fetched before a cancel is still imported. No cover is added (use Calibre's *Generate cover*).

## Metabods Downloader

It builds EPUBs directly from the site's HTML print version (`story_print.php`, the page behind "Print / PDF") rather than converting the PDF, so text, italics and part structure come through cleanly and no PDF conversion step is needed.

- **Download stories by link…**: paste story links, bare story ids, or list pages (author, tag, category, archive), one per line.
- **Search by tag…**: browse the site's tag list with a filter box, check tags, choose *any* or *all* matching, then tick the stories you want. **★ Toggle favorite** saves a highlighted tag; favorites sort first, can be filtered with *Favorites only*, and **Check all favorites** selects them in one click. Favorites and the cached tag list live in Calibre's plugin settings (*Refresh tag list* re-reads the site).
- **Multi-part stories**: all parts of a story are one download and become chapters of a single EPUB with a table of contents. **Combine everything into one book** merges several separate stories into one omnibus EPUB with one nested contents entry per story.
- Imported books get title, author, site tags and category as Calibre tags, the site summary as the comment, publisher *Metabods*, and a `metabods:<story id>` identifier, which **Skip stories already in this library** uses to avoid duplicates. Combined books carry no identifier.
- Images, scripts and most inline styling are dropped; italics, bold, line breaks, indents and centering are kept.

## Nifty Downloader

Nifty is a plain directory tree (section / category / story or series folder) of mail-style text files, one per chapter, with no tags or summaries.

- **Download stories by address…**: paste a story file, a series folder, or a category folder. A link to any chapter downloads the whole series. A bare section (for example `/nifty/gay/`) is refused as too broad.
- **Browse by category…**: pick a section (gay, lesbian, bisexual, transgender) and a category, load its entries, filter by title, and tick what you want. **★ Toggle favorite** saves a category, and a *Favorite categories* drop-down jumps straight to one.
- **Chapters are joined into one book**: files named `name-1`, `name-2`, … (also `chapter05`) are grouped and ordered numerically into one EPUB with a contents entry per chapter. One folder can hold several series; each becomes its own book. The combine option works here too.
- The hard-wrapped text is re-flowed into paragraphs; blocks that look like verse or lists keep their line breaks; `____`, `***` and `---` scene breaks become rules. A few old stories are HTML pages and are cleaned like Metabods text.
- Metadata comes from the mail headers: the title is the Subject with chapter markers and category lists removed, the author is the From name (the email address is dropped), the date becomes the publication date, and the section and category become tags. Publisher is *Nifty*; identifier is `nifty:<path>`.
- **Limits**: old files with no headers get the author *Unknown* and a title taken from the folder or file name. Odd or truncated Subject lines may leave an imperfect title. Nothing is added that the archive does not publish.

## Fanfic Site Downloader

Downloads stories as EPUB using the adapters from [FanFicFare](https://github.com/JimmXinu/FanFicFare) (Apache-2.0), which handle the per-site scraping, chapter lists, series and metadata for 107 sites including Royal Road, Archive of Our Own, FanFiction.Net, Scribble Hub, Wattpad, FimFiction, SpaceBattles and Sufficient Velocity. Use **Supported sites…** in the dialog for the full list. This is the library underneath FanFicFare's Calibre plugin, bundled and driven by this plugin's own dialog; nothing is copied from that plugin (which is GPL-3).

- Paste one story address per line. Addresses are normalised (a chapter link becomes the story link) and duplicates collapse. Add `[1-5]`, `[3-]` or `[-4]` to fetch only those chapters; such partial downloads are titled with their chapter range and are never skipped as duplicates.
- **Allow adult sites** (off by default). Off: stories on adult-only sites are refused before any request is made, and FanFicFare is told `is_adult:false`, so where a mixed site such as Archive of Our Own asks for an adult confirmation, the download fails with a message saying to turn the setting on (I did not see that prompt appear in my AO3 tests, so this path is untested). On: both are allowed and confirmations are given. The list of adult-only sites is hand-curated and deliberately conservative (20 sites, shown with an `[adult]` mark in **Supported sites…**); sites that merely permit adult works are not on it. Add more domains in the dialog. This setting belongs to this plugin only; the Metabods and Nifty downloaders are adult archives and are not gated by it.
- **Advanced settings** takes FanFicFare `personal.ini` text for logins, browser-cache or proxy options. It overrides the defaults, except that the adult setting above always wins.
- Imported books carry FanFicFare's metadata (title, authors, tags, summary, series and index, language, publication date), publisher set to the site, and the same `url` identifier FanFicFare's plugin writes, which should let that plugin recognise and update these books (not verified). Skip-existing matches on that address.
- Downloads run in a background thread; cancelling takes effect between stories because FanFicFare cannot be interrupted partway through a story. FanFicFare paces its own requests (it adds random delays of a few seconds).

**Cloudflare and Royal Road.** Royal Road currently answers non-browser clients with a Cloudflare managed challenge (HTTP 403, `cf-mitigated: challenge`); I confirmed this from the build environment and could not download from it there. Other popular sites (FimFiction, Scribble Hub, Sufficient Velocity) also returned 403 from that environment, which may be about that network rather than the sites. This plugin does not try to defeat such challenges. FanFicFare's own documented options are available through Advanced settings: reading pages from a browser you already use (`use_browser_cache` with `browser_cache_path`, after opening the story in that browser) or a FlareSolverr proxy you run yourself (`use_flaresolverr_proxy`). The bundled `cloudscraper` handles only the older, simpler challenges. When a 403 occurs the plugin says so and points to these options. **Royal Road downloads are untested.** Archive of Our Own downloads were tested through the bundled library.

**Bundling.** The zip carries FanFicFare as a sub-package of this plugin (so it cannot clash with the official FanFicFare plugin if you have both), plus `cloudscraper`, `requests-file`, `requests-toolbelt`, `pyparsing` and a pure-Python Brotli decoder (`third_party/brotlidecpy`, checked against the real compressor), with all licenses in `THIRD_PARTY_LICENSES.txt`. Changes made to bundled code are listed there: relative imports, no command line, EPUB writer only (the text writer needs GPL-3 `html2text`), and a one-line change so `cloudscraper` can read its data file from inside a zip. It relies on Calibre providing `requests`, BeautifulSoup, `html5lib`, `chardet` and `apsw`; I tested the built zip in a clean Python environment containing just those and nothing from FanFicFare, importing every bundled module, and I could not check that against Calibre's own libraries.

## Story Collection Tagger

Adds tags so books from different sites can be organized together. Run **Auto-tag stories** on the selected books or the whole library; **Preview** shows exactly which books would get which tags, and nothing changes until **Apply**. It only adds tags, never removes or renames existing ones, and running it again adds nothing new.

- **Source tag**: each book is matched to a site by an identifier name (`metabods`, `nifty`, `royalroad`, `ao3`, ...), or by the site's address appearing in any identifier value or the publisher. Built in: Metabods, Nifty, and every site FanFicFare has an adapter for (110 in total, including Royal Road, Archive of Our Own, FanFiction.Net, Wattpad, Scribble Hub, Literotica, SpaceBattles, Sufficient Velocity), plus Webnovel, Wuxiaworld, Fur Affinity and Tapas. FanFicFare stores a story's address in the `url` identifier (Calibre writes `:` as `|`) and the site's domain as the publisher; both are recognised, so books added by FanFicFare's own Calibre plugin or by the Fanfic Site Downloader are tagged correctly. Add more as `host => Name` lines. A matching book gets, for example, `Source.Royal Road`; the prefix is editable. To see them as a nested tree, enable hierarchical display for tags in Calibre's *Look & feel → Tag browser* settings. Descriptions are only searched for addresses if you tick the option, since they can over-match.
- **Keyword rules**: lines of `[field:]pattern => Tag, Tag` map what is already on a book to your own cross-site tags. Fields: `tags`, `title`, `author`, `series`, `comments`, `publisher`, `source`, `any`; the default looks at title, tags and series. A plain pattern is a case-insensitive substring, `=text` must match exactly, and `re:...` is a regular expression. For example `tags:=Muscle Growth => Theme.Growth` gives Metabods and other sites' books a shared tag, and `source:Royal Road => Format.Web serial` tags by site.
- **Series tag**: optionally tag every book in a series (`Series.<name>`).
- Books from other tools are tagged if their identifiers or publisher carry the site's address; use the extra-sites box if one is missed.

## Testing

Run `python -m unittest discover -s tests -p "test_*.py" -v`. Offline tests cover the Metabods and Nifty parsers, text cleaning, EPUB structure, the tagger, the fanfic engine and its zip contents, and an import check of each built zip under stubbed Calibre and Qt modules. The fanfic tests need `pip install fanficfare` and skip without it. The one failing test in a plain environment is the older PDF test, which needs PyMuPDF.

Against the live sites: 30 random Metabods stories plus a 50-part one, and 26 Nifty books across all four sections (including a 58-chapter series, `.html` chapter files and odd subjects) all produced well-formed EPUBs. One Archive of Our Own story (chapter 1) was downloaded through the engine from the built zip in a clean environment; Royal Road was not reachable (see above). **Not tested inside Calibre itself** (it was not available here): the dialogs, menus, library import, tag application and refresh. The Calibre calls used (`add_books`, `all_field_for`, `get_metadata`, `set_field`, `refresh_ids`, `JSONConfig`) were checked against Calibre's source on GitHub, and the modules were import-checked against stubs.

