# Gemini Library Fixer

Install: download the ZIP from the [main page](../README.md), then in Calibre choose **Preferences → Plugins → Load plugin from file**, pick it, restart Calibre, and add its button under **Preferences → Toolbars & menus** if it is not visible. Calibre 6 or newer.

Built with `python build_plugins.py` from the repository root (see *Building and testing* on the [main page](../README.md)).

Asks the Google Gemini API to suggest cleaner metadata for the selected books (or the whole library), shows every suggestion, and applies only the ones you leave ticked.

You need a Google AI API key (free keys from [Google AI Studio](https://aistudio.google.com/apikey) have request limits). Paste it into the window, or set `GEMINI_API_KEY` before starting Calibre.

## What it can fix

- **Titles**: removes junk such as `(z-lib.org)`, `[epub]`, file extensions, underscores used as spaces; fixes ALL CAPS / all lower case.
- **Numbered titles**: a title such as `book 1 - the force awakens` (also `Vol. 2: …`, `Part 3 - …`, `#4. …`) loses the marker and becomes `The Force Awakens`, with the number stored as the volume number. The plugin spots these titles itself and tells the model, and books by the same author are sent together so the series name can be recognised from sibling volumes. If the series name cannot be worked out, the title and number are still fixed and the series is left for you to set.
- **Authors**: turns `Last, First` or one joined string into separate `First Last` authors, and will not write "Unknown" back.
- **Series and volume number**: reads them from the title or file name (`Dune Messiah (Dune #2)` becomes series `Dune`, number 2), which also fixes the sort order inside the series.
- **Tags**: merges duplicates and fixes case. By default it can only *add* tags (at most 5 per book); tick *Let it remove or rename existing tags* to allow cleanup.
- **Language**: filled in only when the book has none.

"Rename" and "sort": when a title or author changes, Calibre itself renames the book's folder and files in your library and recomputes the title and author sort values (I checked in Calibre's source that its title and author writers do this). The plugin does not touch file names any other way.

## Safety

- **Preview first.** Nothing changes until you press **Apply ticked changes**. Each book and each field has its own checkbox.
- **Big changes are unticked.** If a new title or author looks like a different book rather than a tidy-up, it is marked BIG CHANGE and left unticked.
- **Confidence filter.** The model rates each book low/medium/high; suggestions below your minimum (default medium) are dropped. Answers are also checked again by the plugin: ids it was not asked about are ignored, lengths and values are limited, and a suggestion equal to the current value is not shown.
- **Undo last run.** The old values of everything applied are saved, and **Undo last run** puts them back (including the old file names). Only the most recent run is kept.
- It never touches book files' contents, covers or descriptions.

## What is sent to Google

Per book: title, authors, series, tags, publisher, language and file names. The first ~1500 characters of an EPUB are sent only if you tick that option. Nothing is sent until you press **Check books**. Your key is stored unencrypted in Calibre's settings folder and is sent only to Google, in a request header.

Google's safety filter can refuse requests with adult content. When a batch is refused, the plugin splits it to find the book responsible and reports that book as "could not be checked"; the rest still work. It does not change Google's safety settings.

## Model

The default model is `gemini-2.5-flash`; **List models** asks Google which models your key can use, and you can type any model name. Requests that hit a rate limit or a server error are retried a few times with a growing pause, then reported.

## Not verified

The request and response handling is covered by offline tests that replace Google with canned answers (rate limits, blocked prompts, truncated output, bad keys, batches, cancel, numbered titles). It has **not** been run against the live Gemini API (no key was available), so how well the model handles your particular books is untested. The window was run under real Qt (PyQt6, offscreen) against a stand-in library for check, apply and undo, but not inside Calibre; the Calibre calls used (`get_metadata`, `formats`, `format_abspath`, `set_field`, `refresh_ids`) were checked against Calibre's source. Try it on two or three books first.
