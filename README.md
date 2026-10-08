# Calibre plugins

Plugins for [Calibre](https://calibre-ebook.com) 6 or newer (Windows, macOS, Linux). To install one: download its ZIP below, then in Calibre choose **Preferences → Plugins → Load plugin from file**, pick the ZIP, and restart Calibre. If the plugin's button is not visible, add it under **Preferences → Toolbars & menus**.

## Available plugins

| Plugin | What it does | Version | Download | Source and docs |
| --- | --- | --- | --- | --- |
| **Takeout Book Fixer** | Recovers books from Google Takeout folders and ZIPs, corrects mislabeled formats (for example EPUBs named `.pdf`), imports them with metadata and covers, repairs mislabeled formats in books already in your library, and can convert image-only PDFs to CBZ comics. | 1.1.0 | [TakeoutBookFixer.zip](https://github.com/Kaleaon/calibre_plugins/raw/main/dist/TakeoutBookFixer.zip) | [`plugin/`](plugin/) · [docs](plugin/README.md) · [validation notes](dist/VALIDATION.md) |
| **EPUB Promo Scrubber** | Removes promotional marks that sites add to EPUBs: "Downloaded from…" lines and banner pages, links to those sites, and site names in metadata. Works on selected library books or on files in a folder; keeps the original by default. | 1.0.0 | [EpubPromoScrubber.zip](https://github.com/Kaleaon/calibre_plugins/raw/main/dist/EpubPromoScrubber.zip) | [`scrubber_plugin/`](scrubber_plugin/) · [docs](scrubber_plugin/README.md) |

## Releases

Tagged releases are listed on the [Releases page](https://github.com/Kaleaon/calibre_plugins/releases). The latest release there is [Takeout Book Fixer v1.0.1](https://github.com/Kaleaon/calibre_plugins/releases/tag/v1.0.1); the ZIPs in the table above are the current versions from `main`, which may be newer than the latest tagged release. EPUB Promo Scrubber has no tagged release yet.

## Status

- Takeout Book Fixer 1.0.1 was validated with Calibre 9.15 on Linux against a real 51-book Takeout sample (see the validation notes). Version 1.1.0 adds the library repair command, which was not part of that validation run.
- EPUB Promo Scrubber has unit tests for its cleaning logic only. The Calibre menu and library-saving code has not been run inside Calibre, and no real-world EPUBs have been tested.

## Building and testing

`python build.py` writes both ZIPs to `dist/`. `python -m unittest discover -s tests -p "test_*.py"` runs the unit tests (the PDF test needs PyMuPDF).
