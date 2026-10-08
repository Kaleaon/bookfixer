# Nifty Downloader

Install: download the ZIP from the [main page](../README.md), then in Calibre choose **Preferences → Plugins → Load plugin from file**, pick it, restart Calibre, and add its button under **Preferences → Toolbars & menus** if it is not visible. Calibre 6 or newer.

Built with `python build_plugins.py` from the repository root (see *Building and testing* on the [main page](../README.md)).

Stories are copyrighted by their authors, and the sites ask that they not be reposted, so this is meant for personal reading copies. Requests are throttled and run in a background thread with a Cancel button; whatever was fetched before a cancel is still imported. No cover is added (use Calibre's *Generate cover*).

Nifty is a plain directory tree (section / category / story or series folder) of mail-style text files, one per chapter, with no tags or summaries.

- **Download stories by address…**: paste a story file, a series folder, or a category folder. A link to any chapter downloads the whole series. A bare section (for example `/nifty/gay/`) is refused as too broad.
- **Browse by category…**: pick a section (gay, lesbian, bisexual, transgender) and a category, load its entries, filter by title, and tick what you want. **★ Toggle favorite** saves a category, and a *Favorite categories* drop-down jumps straight to one.
- **Chapters are joined into one book**: files named `name-1`, `name-2`, … (also `chapter05`) are grouped and ordered numerically into one EPUB with a contents entry per chapter. One folder can hold several series; each becomes its own book. The combine option works here too.
- The hard-wrapped text is re-flowed into paragraphs; blocks that look like verse or lists keep their line breaks; `____`, `***` and `---` scene breaks become rules. A few old stories are HTML pages and are cleaned like Metabods text.
- Metadata comes from the mail headers: the title is the Subject with chapter markers and category lists removed, the author is the From name (the email address is dropped), the date becomes the publication date, and the section and category become tags. Publisher is *Nifty*; identifier is `nifty:<path>`.
- **Limits**: old files with no headers get the author *Unknown* and a title taken from the folder or file name. Odd or truncated Subject lines may leave an imperfect title. Nothing is added that the archive does not publish.
