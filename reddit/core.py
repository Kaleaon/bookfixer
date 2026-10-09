"""Following stories on Reddit: sources, feed and API parsing, a chapter cache, and building the book.

Pure standard library so it can be tested outside Calibre. Reddit is reached in one of two ways: its official API with the
user's own credentials (recommended), or its public Atom feeds read the way a feed reader would (see README for the
trade-offs). Requests are infrequent, one page at a time, and a rate limit (HTTP 429) ends the run instead of being retried.
"""
import base64
import html
import json
import os
import re
import time
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, urlencode, urlparse

try:  # inside Calibre the shared module ships in the plugin package
    from .storykit import Cancelled, Fetcher, RateLimited, build_epub as _build_epub, clean_fragment, escape, strip_tags  # noqa: F401
except ImportError:  # tests load this file directly with common/ on sys.path
    from storykit import Cancelled, Fetcher, RateLimited, build_epub as _build_epub, clean_fragment, escape, strip_tags  # noqa: F401

WWW = 'https://www.reddit.com'
OAUTH = 'https://oauth.reddit.com'
TOKEN_URL = 'https://www.reddit.com/api/v1/access_token'
FEED_USER_AGENT = 'CalibreRedditFollower/1.0 (personal feed reader; polls rarely)'
PUBLISHER = 'Reddit'
MIN_CHECK_HOURS = 1.0
MIN_FEED_INTERVAL = 7.0       # seconds between requests without credentials (Reddit has allowed roughly 10 a minute)
MIN_API_INTERVAL = 2.0        # seconds between requests through the official API
FIRST_RUN_PAGES = 30         # newest 3000 posts at most per backfill pass; a longer history is finished by the next check
NOTE_BATCH = 300             # author comments fetched per check (one request each); the rest follow on the next checks
EACH_FIRST_RUN = 25          # 'each post is a book' follows add only the newest few on the first check, not a whole backlog
EACH_FIRST_PAGES = 5
EACH_PER_RUN = 50            # books added to the library per check
NOTES_GAP_HOURS = 0.25       # how soon a check that still owes author comments may run again
NAV_WORDS = r'(?:first|previous|prev|next|latest|last|index|wiki|series|home|start|final|chapter|part|start here|table of contents|toc)'


class SourceError(ValueError):
    """The address the user gave is not something we can follow."""


# ---------------------------------------------------------------- what to follow

_NAME = r'[A-Za-z0-9_\-]{2,32}'


def parse_source(text):
    """Turn a pasted address or shorthand into {'kind', 'subreddit', 'user', 'query'}.

    Accepts r/HFY, /r/hfy/new, https://www.reddit.com/r/HFY/, u/name, /user/name/submitted, and search addresses such as
    https://www.reddit.com/r/HFY/search/?q=Out+of+Cruel+Space&restrict_sr=1."""
    raw = (text or '').strip()
    if not raw:
        raise SourceError('Enter a subreddit (r/HFY), a user (u/name) or a Reddit search address.')
    if '://' not in raw and not raw.startswith('/'):
        raw = ('/' + raw) if re.match(r'(?i)^(r|u|user)/', raw) else raw
    if '://' in raw or re.match(r'(?i)^(www\.|old\.|new\.)?reddit\.com', raw):
        if '://' not in raw:
            raw = 'https://' + raw
        parsed = urlparse(raw)
        if not (parsed.netloc.lower().endswith('reddit.com') or parsed.netloc.lower() == 'redd.it'):
            raise SourceError('That is not a Reddit address.')
        path, query = parsed.path, parse_qs(parsed.query)
    else:
        path, query = raw, {}
    path = re.sub(r'\.(rss|json)$', '', path.rstrip('/'))
    m_sub = re.match(r'(?i)^/r/(' + _NAME + r')(/.*)?$', path)
    m_user = re.match(r'(?i)^/(?:u|user)/(' + _NAME + r')(/.*)?$', path)
    if m_sub and (m_sub.group(2) or '').lower().startswith('/search') or (m_sub and query.get('q')):
        q = (query.get('q') or [''])[0].strip()
        if not q:
            raise SourceError('That search address has no search words (q=...).')
        return {'kind': 'search', 'subreddit': m_sub.group(1), 'user': '', 'query': q}
    if m_sub:
        if (m_sub.group(2) or '').lower().startswith('/comments'):
            raise SourceError('That is a single post. Follow the subreddit, the author, or a search instead.')
        return {'kind': 'subreddit', 'subreddit': m_sub.group(1), 'user': '', 'query': ''}
    if m_user:
        return {'kind': 'user', 'subreddit': '', 'user': m_user.group(1), 'query': ''}
    if path.lower().startswith('/search') and query.get('q'):
        return {'kind': 'search', 'subreddit': '', 'user': '', 'query': query['q'][0].strip()}
    raise SourceError('Could not tell what to follow. Use r/NAME, u/NAME, or a Reddit search address.')


def describe_source(src):
    if src['kind'] == 'subreddit':
        return f"r/{src['subreddit']}"
    if src['kind'] == 'user':
        return f"u/{src['user']}"
    return f"search “{src['query']}”" + (f" in r/{src['subreddit']}" if src['subreddit'] else '')


# Ready-made follows for series the user asked for. Authors and title patterns were read from the series' own first post.
PRESETS = [
    {'label': 'Out of Cruel Space (r/HFY, by KyleKKent)', 'name': 'Out of Cruel Space', 'source': 'u/KyleKKent',
     # the author renamed the series part-way: "Out of Cruel Space, Part N" became "OOCS, Into A Wider Galaxy, Part N"
     'title_filter': 're:^\\s*(Out of Cruel Space|OOCS)\\b.*\\d', 'author_filter': 'KyleKKent'},
    # many authors, one story per post, each with a flair; every post becomes its own book (newest few on the first check)
    {'label': 'r/gayincest_stories (each post as its own book)', 'name': 'r/gayincest_stories', 'source': 'r/gayincest_stories',
     'title_filter': '', 'author_filter': '', 'flair_filter': '', 'layout': 'each'},
]


def source_text(src):
    """The source as an address parse_source() reads back, for filling in the edit box."""
    if src['kind'] == 'subreddit':
        return f"r/{src['subreddit']}"
    if src['kind'] == 'user':
        return f"u/{src['user']}"
    base = f"{WWW}/r/{src['subreddit']}/search/" if src['subreddit'] else f'{WWW}/search/'
    params = {'q': src['query']}
    if src['subreddit']:
        params['restrict_sr'] = '1'
    return f'{base}?{urlencode(params, quote_via=quote)}'


def _listing_path(src):
    if src['kind'] == 'subreddit':
        return f"/r/{src['subreddit']}/new", {}
    if src['kind'] == 'user':
        return f"/user/{src['user']}/submitted", {'sort': 'new'}
    base = f"/r/{src['subreddit']}/search" if src['subreddit'] else '/search'
    params = {'q': src['query'], 'sort': 'new'}
    if src['subreddit']:
        params['restrict_sr'] = 'on'
    return base, params


def feed_url(src, limit=100, after=None):
    path, params = _listing_path(src)
    params = dict(params, limit=limit)
    if after:
        params['after'] = after
    return f'{WWW}{path}.rss?{urlencode(params, quote_via=quote)}'


def api_path(src, limit=100, after=None):
    path, params = _listing_path(src)
    params = dict(params, limit=limit, raw_json=1)
    if src['kind'] == 'search':
        params['type'] = 'link'
    if after:
        params['after'] = after
    return f'{path}?{urlencode(params, quote_via=quote)}'


# ---------------------------------------------------------------- cleaning post HTML

_MD = re.compile(r'<div class="md">(.*?)</div>\s*<!--\s*SC_ON\s*-->', re.S)
_MD_LOOSE = re.compile(r'<div class="md">(.*)</div>', re.S)
_NAV_ONLY = re.compile(r'(?i)^[\s|/•·\-–—>»«\[\]()←→,.:]*(?:' + NAV_WORDS + r'[\s|/•·\-–—>»«\[\]()←→,.:\d]*)+$')


def main_html(content):
    """The post body from a feed entry or an API selftext_html: drops Reddit's wrapper and the 'submitted by ...' footer."""
    content = html.unescape(content) if '&lt;div' in content and '<div' not in content else content
    m = _MD.search(content) or _MD_LOOSE.search(content)
    body = m.group(1) if m else re.split(r'(?i)(?:&#32;|\s)*submitted\s+by\b', content)[0]
    cleaned = strip_navigation(clean_fragment(body))
    return cleaned if strip_tags(cleaned).strip() else ''  # image and link posts leave only empty markup


_BLOCK = re.compile(r'<p(?: [^>]*)?>.*?</p>|<hr/>|<(?P<tag>div|blockquote|ul|ol|pre|h[1-6])(?: [^>]*)?>.*?</(?P=tag)>', re.S)


def strip_navigation(xhtml):
    """Remove 'First | Previous | Next' style link lines from the start and end of a post, and any rule beside them.

    Works on whole top-level blocks. If the text does not split cleanly into blocks it is returned unchanged."""
    blocks, position = [], 0
    for m in _BLOCK.finditer(xhtml):
        if xhtml[position:m.start()].strip():
            return xhtml.strip()  # loose text between blocks: not something we can split safely
        blocks.append(m.group(0))
        position = m.end()
    if xhtml[position:].strip():
        return xhtml.strip()

    def removable(block):
        if block == '<hr/>':
            return True
        text = strip_tags(block)
        return block.startswith('<p') and bool(text) and bool(_NAV_ONLY.match(text))

    while blocks and removable(blocks[-1]):
        blocks.pop()
    while blocks and removable(blocks[0]):
        blocks.pop(0)
    return ''.join(blocks)


# ---------------------------------------------------------------- reading feeds and API listings

def _epoch(text):
    text = (text or '').strip().replace('Z', '+00:00')
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return 0.0
    return (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).timestamp()


def parse_atom(xml_text):
    """Entries of a Reddit Atom feed. Returns (entries, after) where after is the id to pass for the next, older page."""
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f'The feed was not readable XML ({exc}). Reddit may have refused the request.') from exc
    entries = []
    for e in root.findall('a:entry', ns):
        raw_id = (e.findtext('a:id', namespaces=ns) or '').strip()
        if not re.match(r'^t3_\w+$', raw_id):
            continue  # comments and other kinds
        link = e.find('a:link', ns)
        author = (e.findtext('a:author/a:name', namespaces=ns) or '').strip()
        content = e.findtext('a:content', namespaces=ns) or ''
        entries.append({
            'id': raw_id,
            'title': html.unescape((e.findtext('a:title', namespaces=ns) or '').strip()),
            'author': re.sub(r'^/?u/', '', author),
            'created': _epoch(e.findtext('a:published', namespaces=ns) or e.findtext('a:updated', namespaces=ns)),
            'link': link.get('href') if link is not None else '',
            'html': main_html(content) if '<div class="md">' in content or 'submitted by' in content else '',
            'subreddit': (e.find('a:category', ns).get('term') if e.find('a:category', ns) is not None else ''),
        })
    return entries, (entries[-1]['id'] if entries else None)


def parse_listing(json_text):
    """Entries of an API listing. Returns (entries, after) where after is the listing's own 'after' token."""
    data = json.loads(json_text)
    listing = data.get('data', {}) if isinstance(data, dict) else {}
    entries = []
    for child in listing.get('children', []):
        d = child.get('data', {}) if child.get('kind') == 't3' else {}
        if not d.get('name'):
            continue
        entries.append({
            'id': d['name'], 'title': html.unescape(d.get('title', '')), 'author': d.get('author', ''),
            'created': float(d.get('created_utc') or 0),
            'link': 'https://www.reddit.com' + d.get('permalink', ''),
            'html': main_html(d['selftext_html']) if d.get('selftext_html') else '',
            'subreddit': d.get('subreddit', ''), 'flair': (d.get('link_flair_text') or '').strip(),
        })
    return entries, listing.get('after')


class FeedSource:
    """Reads pages of posts from public Atom feeds (no credentials)."""
    mode = 'rss'

    def __init__(self, fetcher):
        self.fetcher = fetcher

    def page(self, src, after=None, limit=100):
        text = self.fetcher.get(feed_url(src, limit, after), headers={'User-Agent': FEED_USER_AGENT, 'Accept': 'application/atom+xml, application/xml'})
        return parse_atom(text)


class ApiSource:
    """Reads pages of posts through Reddit's official API with the user's own app.

    With a saved login (a refresh token from "Log in with Reddit") it acts as that account; otherwise with only a client id
    (an 'installed app') it uses the installed-client grant, and with a secret it uses client credentials.
    Written against Reddit's documented API and tested with a stand-in server; not verified against the live service."""
    mode = 'api'

    def __init__(self, fetcher, client_id, client_secret='', username='', token_url=None, base=None, refresh_token=''):
        self.fetcher, self.client_id, self.client_secret = fetcher, client_id.strip(), (client_secret or '').strip()
        self.token_url, self.base = token_url or TOKEN_URL, base or OAUTH
        self.refresh_token = (refresh_token or '').strip()
        self.user_agent = f"calibre:reddit-follower:1.0 (by /u/{(username or 'unknown').strip().lstrip('/').replace('u/', '')})"
        self._token, self._expires = None, 0.0
        self._device = uuid.uuid4().hex

    def _authorize(self):
        if not self.client_id:
            raise SourceError('Enter your Reddit app\'s client id in the settings to use the official API.')
        basic = base64.b64encode(f'{self.client_id}:{self.client_secret}'.encode()).decode()
        if self.refresh_token:
            body = urlencode({'grant_type': 'refresh_token', 'refresh_token': self.refresh_token})
        elif self.client_secret:
            body = urlencode({'grant_type': 'client_credentials'})
        else:
            body = urlencode({'grant_type': 'https://oauth.reddit.com/grants/installed_client', 'device_id': self._device})
        reply = json.loads(self.fetcher.get(self.token_url, post=body.encode(), headers={
            'Authorization': f'Basic {basic}', 'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': self.user_agent}))
        if not reply.get('access_token'):
            if self.refresh_token:
                raise SourceError('Reddit no longer accepts the saved login. Open Settings and log in with Reddit again.')
            raise IOError(f"Reddit refused the credentials: {reply.get('error') or reply.get('message') or reply}")
        self._token = reply['access_token']
        self._expires = time.monotonic() + float(reply.get('expires_in', 3600)) - 60

    def page(self, src, after=None, limit=100):
        if not self._token or time.monotonic() >= self._expires:
            self._authorize()
        try:
            text = self.fetcher.get(self.base + api_path(src, limit, after), headers={'Authorization': f'bearer {self._token}', 'User-Agent': self.user_agent})
        except IOError as exc:
            if 'HTTP Error 403' in str(exc) and 'insufficient_scope' in str(exc) and self.refresh_token:
                raise SourceError('Reddit says the saved login lacks permission for this page. Open Settings, Log out, then Log in with '
                                  'Reddit again to grant it.') from exc
            raise
        return parse_listing(text)


    def author_comment(self, entry):
        """The post author's own top-level comment as cleaned HTML ('' if there is none). One request."""
        if not self._token or time.monotonic() >= self._expires:
            self._authorize()
        post_id = entry['id'].split('_', 1)[-1]
        text = self.fetcher.get(f"{self.base}/comments/{post_id}?limit=100&depth=1&sort=top&raw_json=1",
                                headers={'Authorization': f'bearer {self._token}', 'User-Agent': self.user_agent})
        return top_level_author_comment(text, entry.get('author', ''))


def top_level_author_comment(json_text, author):
    data = json.loads(json_text)
    if not (isinstance(data, list) and len(data) > 1):
        return ''
    for child in data[1].get('data', {}).get('children', []):
        d = child.get('data', {}) if child.get('kind') == 't1' else {}
        if author and d.get('author', '').casefold() == author.casefold() and d.get('body_html'):
            return main_html(d['body_html'])
    return ''


def make_source(mode, client_id='', client_secret='', username='', cancelled=lambda: False, refresh_token=''):
    """The reader for the chosen mode, paced so as to stay within Reddit's limits for that mode."""
    if mode == 'api':
        return ApiSource(Fetcher(min_interval=MIN_API_INTERVAL, cancelled=cancelled), client_id, client_secret, username,
                         refresh_token=refresh_token)
    return FeedSource(Fetcher(min_interval=MIN_FEED_INTERVAL, cancelled=cancelled))


def probe(source, src, follow=None, limit=25):
    """Make ONE request and say what came back. Returns (ok, message); never raises for network or format problems."""
    try:
        entries, _ = source.page(src, None, limit)
    except RateLimited as exc:
        wait = f' It asked for about {max(1, round(exc.retry_after / 60))} minute(s).' if exc.retry_after else ''
        return False, ('Reddit asked us to slow down (HTTP 429).' + wait + ' Shared and cloud networks hit this far more often than a home '
                       'connection. Wait a while and try again; the plugin itself will back off the same way.')
    except SourceError as exc:
        return False, str(exc)
    except (IOError, ValueError) as exc:
        return False, f'Reddit did not give a usable answer: {exc}'
    if not entries:
        return True, f'Reddit answered, but {describe_source(src)} returned no posts.'
    with_text = [e for e in entries if e.get('html')]
    parts = [f'Reddit answered through the {"official API" if source.mode == "api" else "public feed"}: {len(entries)} post(s), '
             f'{len(with_text)} with story text']
    if follow is not None:
        mine = [e for e in entries if matches(e, follow)]
        parts.append(f'{len(mine)} match your filters' + (f', newest \u201c{max(mine, key=lambda e: e["created"])["title"]}\u201d' if mine else
                                                          ' (none on this first page; the first check reads further back)'))
    return True, '; '.join(parts) + '.'


# ---------------------------------------------------------------- follows, filters, and the chapter cache

def new_follow(name, source_text, title_filter='', author_filter='', author_note=False, layout='series', flair_filter=''):
    src = parse_source(source_text)
    return {'id': uuid.uuid4().hex[:10], 'name': name.strip() or describe_source(src), 'source': src,
            'title_filter': title_filter.strip(), 'author_filter': author_filter.strip().lstrip('/').replace('u/', '', 1),
            'author_note': bool(author_note), 'layout': 'each' if layout == 'each' else 'series', 'flair_filter': flair_filter.strip(),
            'last_checked': 0.0, 'last_status': ''}


def matches(entry, follow):
    """Whether a post belongs to the followed series. Text posts only; filters are case-insensitive."""
    if not entry.get('html') or not entry.get('title'):
        return False  # link, image and empty posts have no story text
    flt = follow.get('title_filter', '')
    if flt:
        if flt.lower().startswith('re:'):
            try:
                if not re.search(flt[3:], entry['title'], re.I):
                    return False
            except re.error:
                return False
        elif flt.casefold() not in entry['title'].casefold():
            return False
    if not _text_matches(follow.get('flair_filter', ''), entry.get('flair', '')):
        return False
    if follow.get('layout') == 'each' and stated_minor_age(entry['title']):
        return False
    author = follow.get('author_filter', '')
    return not author or entry.get('author', '').casefold() == author.casefold()


def _text_matches(flt, text):
    if not flt:
        return True
    if flt.lower().startswith('re:'):
        try:
            return bool(re.search(flt[3:], text, re.I))
        except re.error:
            return False
    return flt.casefold() in text.casefold()


_AGE_TAGS = re.compile(r'[\[(]\s*[mfMF]?\s*(\d{1,2})\s*[mfMF]?\s*[\])]')
_AGE_WORDS = re.compile(r'(?i)\b(\d{1,2})\s*(?:yo|y/o|y\.o\.|years?[ -]old)\b')
_AGE_LETTER = re.compile(r'(?i)\b(\d{1,2})\s?[mf]\b')


def stated_minor_age(title):
    """True if the title states an age under 18 (such as [16M], (17), 15 yo). A title-only check: it cannot know about ages
    that are not in the title, and a bracketed number that is not an age (a part number) counts too, so it errs on the side
    of skipping. Applied to 'each post is a book' follows, which take posts from many authors."""
    for pattern in (_AGE_TAGS, _AGE_WORDS, _AGE_LETTER):
        for m in pattern.finditer(title):
            if 1 <= int(m.group(1)) < 18:
                return True
    return False


class ChapterCache:
    """Posts already fetched for one followed series, kept as a JSON file so the whole book can be rebuilt offline."""

    def __init__(self, folder, follow_id):
        self.path = os.path.join(folder, f'{follow_id}.json')
        self.data = {'posts': {}, 'newest_created': 0.0, 'newest_id': ''}
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding='utf-8') as stream:
                    self.data.update(json.load(stream))
            except (OSError, ValueError):
                pass  # a damaged cache is rebuilt by the next check

    @property
    def posts(self):
        return self.data['posts']

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as stream:
            json.dump(self.data, stream)
        os.replace(tmp, self.path)

    def ordered(self):
        return sorted(self.posts.values(), key=lambda p: (p['created'], p['title']))

    def delete(self):
        try:
            os.remove(self.path)
        except OSError:
            pass


def check_follow(source, follow, cache, max_pages=None, cancelled=lambda: False, progress=lambda msg: None):
    """Fetch new posts for one follow into the cache. Returns {'new': [titles], 'changed': [titles], 'pages': n}.

    The first check pages back through the feed; later checks read only until they reach posts seen before. A
    RateLimited error propagates after the cache has been saved with whatever was read."""
    src = follow['source']
    # a history is "complete" once a pass has read all the way back; until then each check keeps backfilling (older caches
    # from before this was tracked count as incomplete, so they are topped up once)
    signature = [follow.get('title_filter', ''), follow.get('author_filter', ''), source_text(src), follow.get('flair_filter', ''),
                 follow.get('layout', 'series')]
    if cache.data.get('signature') != signature:
        cache.data['complete'] = False  # the filters changed, so older posts may now belong
        cache.data['signature'] = signature
    first_run = not cache.data.get('complete')
    each = follow.get('layout') == 'each'
    max_pages = max_pages or ((EACH_FIRST_PAGES if each else FIRST_RUN_PAGES) if first_run else 3)
    known_newest, known_id = cache.data['newest_created'], cache.data['newest_id']
    new, changed, after, pages, newest = [], [], None, 0, (0.0, '')
    try:
        while pages < max_pages:
            if cancelled():
                raise Cancelled()
            progress(f"{follow['name']}: reading page {pages + 1}")
            entries, after = source.page(src, after)
            pages += 1
            reached_known = False
            for e in entries:
                if (e['created'], e['id']) > newest:
                    newest = (e['created'], e['id'])
                if not first_run and (e['id'] == known_id or (known_newest and e['created'] < known_newest - 1)):
                    reached_known = True
                if not first_run and known_newest and e['created'] < known_newest - 1 and e['id'] not in cache.posts:
                    continue  # older than anything collected and never kept: not part of this check ('each' follows skip their backlog on purpose)
                if not matches(e, follow):
                    continue
                old = cache.posts.get(e['id'])
                if old is None:
                    new.append(e['title'])
                elif old['html'] != e['html'] or old['title'] != e['title']:
                    changed.append(e['title'])
                    if e['id'] in cache.data.get('added', []):
                        cache.data['added'].remove(e['id'])  # an edited post becomes a fresh book
                else:
                    continue
                cache.posts[e['id']] = {k: e.get(k, '') for k in ('id', 'title', 'author', 'created', 'link', 'html', 'flair')}
                if old is not None and 'note' in old:
                    cache.posts[e['id']]['note'] = old['note']
            if not entries or not after or reached_known:
                if first_run and (not entries or not after):
                    cache.data['complete'] = True
                break
        if each and first_run:
            cache.data['complete'] = True  # never backfills; only the newest few are taken
            keep = {p['id'] for p in sorted(cache.posts.values(), key=lambda p: p['created'], reverse=True)[:EACH_FIRST_RUN]}
            for post_id in [i for i in cache.posts if i not in keep]:
                del cache.posts[post_id]
            new = [t for t in new if any(p['title'] == t for p in cache.posts.values())]
    finally:
        if newest[0]:
            cache.data['newest_created'], cache.data['newest_id'] = max(known_newest, newest[0]), newest[1] if newest[0] >= known_newest else known_id
        cache.save()
    pending = fetch_notes(source, follow, cache, cancelled, progress)
    return {'new': new, 'changed': changed, 'pages': pages, 'notes_pending': pending}


def fetch_notes(source, follow, cache, cancelled=lambda: False, progress=lambda msg: None, batch=None):
    """Fetch the author's own comment for cached chapters that lack one (only when the follow asks for it and the reader is
    the API). Returns how many chapters still wait. A rate limit propagates after the cache is saved."""
    if not follow.get('author_note') or not hasattr(source, 'author_comment'):
        return 0
    todo = [p for p in sorted(cache.posts.values(), key=lambda p: p['created'], reverse=True) if 'note' not in p]
    done = 0
    try:
        for post in todo[:batch or NOTE_BATCH]:
            if cancelled():
                raise Cancelled()
            progress(f"{follow['name']}: author comment {done + 1} of {min(len(todo), batch or NOTE_BATCH)}")
            post['note'] = source.author_comment(post)
            done += 1
    finally:
        if done:
            cache.save()
    return len(todo) - done


def chapter_html(post):
    body = post['html'] or '<p>(empty)</p>'
    if post.get('note'):
        body += '<hr/><p><em>Author\'s comment</em></p>' + post['note']
    return body


def build_story(follow, cache):
    """A story dict for storykit.build_epub from everything cached: one chapter per post, oldest first."""
    posts = cache.ordered()
    if not posts:
        raise ValueError('Nothing has been collected for this series yet.')
    author = Counter(p['author'] for p in posts).most_common(1)[0][0] or 'Unknown'
    last = datetime.fromtimestamp(posts[-1]['created'], timezone.utc).date().isoformat()
    first = datetime.fromtimestamp(posts[0]['created'], timezone.utc).date().isoformat()
    src = follow['source']
    tags = ['Reddit'] + ([f"r/{src['subreddit']}"] if src.get('subreddit') else [])
    return {'id': 'reddit-' + follow['id'], 'url': posts[-1]['link'] or WWW, 'title': follow['name'], 'author': author,
            'sections': [(p['title'], chapter_html(p)) for p in posts], 'tags': tags, 'categories': [],
            'summary': f"{len(posts)} chapters collected from Reddit ({describe_source(src)}), {first} to {last}.",
            'publisher': PUBLISHER, 'pubdate': first}


_PART = re.compile(r"(?i)^(?P<stem>.*?)[\s,:;\-\u2013\u2014(\[]*\b(?:part|pt\.?|chapter|ch\.?)\s*(?P<n>\d+)\b")


def build_each(follow, post):
    """One post as its own story dict: flair becomes tags ('TRUE STORY - Uncle' -> 'TRUE STORY', 'Uncle'), and a title like
    'Name, Part 3' joins the Calibre series 'Name' (index 3)."""
    m = re.search(r'/r/([^/]+)/', post.get('link', ''))
    tags = ['Reddit'] + ([f'r/{m.group(1)}'] if m else [])
    for piece in re.split(r'\s+[-\u2013\u2014]\s+', post.get('flair', '')):
        if piece.strip():
            tags.append(piece.strip())
    story = {'id': 'reddit-' + post['id'], 'url': post.get('link') or WWW, 'title': post['title'], 'author': post.get('author') or 'Unknown',
             'sections': [(post['title'], chapter_html(post))], 'tags': list(dict.fromkeys(tags)), 'categories': [], 'summary': '',
             'publisher': PUBLISHER,
             'pubdate': datetime.fromtimestamp(post['created'], timezone.utc).date().isoformat()}
    part = _PART.match(post['title'])
    if part and len(re.sub(r'\W', '', part.group('stem'))) >= 4:
        story['series'], story['series_index'] = part.group('stem').strip(' ,:;-\u2013\u2014'), float(part.group('n'))
    return story


def pending_each(follow, cache, limit=None):
    """Cached posts not yet made into library books, oldest first (at most `limit`)."""
    added = set(cache.data.get('added', []))
    return [p for p in cache.ordered() if p['id'] not in added][:limit or EACH_PER_RUN]


def build_epub(story):
    return _build_epub([story], title=story['title'], publisher=PUBLISHER)


# ---------------------------------------------------------------- running checks for several follows

def due(follow, hours, now=None):
    """Whether a follow has not been checked within the interval. Never less often than MIN_CHECK_HOURS apart."""
    if not follow.get('last_checked'):
        return True  # never checked
    now = time.time() if now is None else now
    if follow.get('notes_pending'):
        hours = NOTES_GAP_HOURS  # still collecting author comments: carry on soon, a few pages of listing per check
        return now - follow['last_checked'] >= hours * 3600
    return now - follow['last_checked'] >= max(hours, MIN_CHECK_HOURS) * 3600


def run_follows(source, follows, cache_dir, cancelled=lambda: False, progress=lambda msg: None, now=time.time):
    """Check each follow in turn. Returns a list of {'follow', 'new', 'changed', 'error', 'rate_limited', 'retry_after'}.

    A rate limit ends the whole run (the remaining follows are reported as skipped) because the limit applies to
    every request we make. Whatever was read before the limit is kept in the cache."""
    results = []
    for index, follow in enumerate(follows):
        result = {'follow': follow, 'new': [], 'changed': [], 'error': '', 'rate_limited': False, 'retry_after': None, 'skipped': False}
        cache = ChapterCache(cache_dir, follow['id'])
        try:
            outcome = check_follow(source, follow, cache, cancelled=cancelled, progress=progress)
            result['new'], result['changed'] = outcome['new'], outcome['changed']
            follow['last_checked'] = now()
            follow['notes_pending'] = bool(outcome['notes_pending'])
            follow['last_status'] = (f"{len(outcome['new'])} new chapter(s)" if outcome['new'] else 'up to date')
            if outcome['notes_pending']:
                follow['last_status'] += f"; {outcome['notes_pending']} author comment(s) still to fetch"
            elif follow.get('author_note') and not hasattr(source, 'author_comment'):
                follow['last_status'] += '; author comments need the official API'
        except RateLimited as exc:
            result.update(rate_limited=True, retry_after=exc.retry_after, error=str(exc))
            follow['last_status'] = 'Reddit asked us to slow down; will try again later'
            results.append(result)
            results.extend({'follow': f, 'new': [], 'changed': [], 'error': '', 'rate_limited': False, 'retry_after': None, 'skipped': True}
                           for f in follows[index + 1:])
            return results
        except Cancelled:
            raise
        except (IOError, ValueError) as exc:
            result['error'] = str(exc)
            follow['last_status'] = f'error: {exc}'[:200]
        results.append(result)
    return results
