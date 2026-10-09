# Reddit Story Follower

Install: download the ZIP from the [main page](../README.md), then in Calibre choose **Preferences → Plugins → Load plugin from file**, pick it, restart Calibre, and add its button under **Preferences → Toolbars & menus** if it is not visible. Calibre 6 or newer.

Built with `python build_plugins.py` from the repository root (see *Building and testing* on the [main page](../README.md)).

Follows story series that are posted on Reddit, such as chapters in r/HFY, as a **single EPUB per series that grows** as new chapters appear. Each matching post becomes a chapter, oldest first, with a contents list. When new posts arrive the book in your library is updated in place.

## Using it

1. Click **Reddit stories → Followed stories… → Add…**
2. **Book title**: what the book will be called, for example *Out of Cruel Space*.
3. **Where to look**: one of
   - a subreddit: `r/HFY`
   - an author: `u/name` (their submitted posts)
   - a Reddit search address: search the series name inside the subreddit on Reddit, then paste the address of the results page. This is the best way to follow one series in a busy subreddit.
4. **Title contains** (and optionally **Posted by**): keeps only the posts that belong to the series, for example `Out of Cruel Space`. Start the text with `re:` for a regular expression, such as `re:chapter\s+\d+`.
5. Press **Check selected now**. The first check reads back through the feed; later checks read only until they reach posts they have already seen.

**Out of Cruel Space:** I could not identify its author from public information, so I did not hard-code anything. Use a search address for r/HFY with *Title contains* `Out of Cruel Space`, or follow the author's `u/name` if you know it.

## Automatic updates

While Calibre is open, the plugin looks every 15 minutes at which followed stories are due (this costs nothing) and quietly checks the ones that are, in a background thread. A status-bar note appears when a book was updated. Your **settings** control this:

- **Check each story at most every N hours**: default 6, never shorter than 1 hour.
- Automatic checking can be switched off; **Check for new chapters now** always works.
- There is **no background service**: nothing is checked while Calibre is closed. The first automatic check runs about two minutes after Calibre starts.
- If Reddit answers HTTP 429 (slow down), the run stops at once, keeps what it already read, and leaves Reddit alone for at least 15 minutes (longer if Reddit says so). It never retries into a rate limit.

If you delete a followed book from your library, the next check rebuilds it from the chapters the plugin has kept (in Calibre's `plugins/reddit_follower_cache` folder). Removing a story from the list deletes its kept chapters but never the book.

## Two ways to read Reddit, and what is known about each

| | Public feeds (default) | Official API (your own credentials) |
| --- | --- | --- |
| Needs | nothing | a Reddit app's client id (and secret, for a "script" app) |
| Reach | the newest posts only (up to 100 per page, up to 10 pages on the first check) | the same, through the API |
| Pace | one request every 7 seconds | one request every 2 seconds |
| Status | **read the way a feed reader does**; Reddit's `robots.txt` asks automated clients to stay out of the whole site, and Reddit answers repeated requests with HTTP 429 | the route Reddit documents; new API access now needs Reddit's approval (its Responsible Builder Policy) |

Choose the API if you have, or can get, approval from Reddit: it is the supported route. I could not confirm Reddit's current approval process from Reddit's own pages; look at its developer documentation before relying on it. The public-feed route is light and personal, and is offered for people without API access; whether it fits Reddit's rules for your use is your call, and Reddit may block it at any time.

## What was and was not verified

- Verified against a **real r/HFY feed**: the Atom parser read 25 posts correctly, each with its full story text (4 to 26 KB), author, date and next-page token.
- **Not verified live**: the search-feed form and the page-by-page backfill (Reddit rate-limited my test requests, and I stopped rather than push it), and the whole **official API path** (no credentials were available). The API code is written to Reddit's documentation and tested against a stand-in server.
- Verified with real Qt and a stand-in Calibre library: creating a book, updating it in place when a chapter arrives, leaving it alone when nothing changed, recreating it after you delete it, backing off after a rate limit, and the automatic background check respecting the schedule. **Not run inside Calibre itself.**

## Limits

- Text posts only. Image and link posts have no story text and are skipped; images inside posts are dropped. Comments are not collected.
- The feed reaches back about 1,000 posts at most (fewer in a busy subreddit if the series is old). Use an author or search source to stay within that, and expect very old chapters to be missed.
- A chapter that its author edits is refreshed only when it is read again within the newest pages.
- "First | Previous | Next" navigation lines at the start or end of a post are removed; other text is left exactly as posted.
- Reddit content belongs to its authors and is subject to Reddit's terms; this is meant for personal reading copies.
