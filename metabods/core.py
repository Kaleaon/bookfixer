"""Metabods fetching, parsing and EPUB building. Pure standard library so it can be tested outside Calibre."""
import gzip
import html
import re
import time
import uuid
import zipfile
from html.parser import HTMLParser
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape, quoteattr

SITE = 'https://metabods.com/mbxy/site/'
USER_AGENT = 'Mozilla/5.0 (compatible; CalibreMetabodsDownloader/1.0; personal use)'
MIN_INTERVAL = 1.0  # seconds between requests, to stay polite to a small hobby site
MAX_BYTES = 64 * 1024 * 1024


class Cancelled(Exception):
    pass


class Fetcher:
    """Throttled HTTP GET with retries, gzip support and cooperative cancellation."""

    def __init__(self, min_interval=MIN_INTERVAL, cancelled=lambda: False, opener=urlopen):
        self.min_interval = min_interval
        self.cancelled = cancelled
        self.opener = opener
        self._last = 0.0

    def get(self, url, retries=3):
        last_error = None
        for attempt in range(retries):
            if self.cancelled():
                raise Cancelled()
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                req = Request(url, headers={'User-Agent': USER_AGENT, 'Accept-Encoding': 'gzip'})
                with self.opener(req, timeout=60) as resp:
                    raw = resp.read(MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES:
                        raise ValueError('Response too large')
                    if resp.headers.get('Content-Encoding', '').lower() == 'gzip':
                        raw = gzip.decompress(raw)
                    return decode(raw, resp.headers.get_content_charset())
            except HTTPError as exc:
                last_error = exc
                if exc.code in (400, 401, 403, 404, 410):
                    break  # retrying will not help
            except (URLError, OSError, EOFError) as exc:
                last_error = exc
            time.sleep(2 ** attempt)
        raise IOError(f'Could not fetch {url}: {last_error}')


def decode(raw, charset=None):
    for enc in ([charset] if charset else []) + ['utf-8', 'cp1252']:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode('utf-8', 'replace')


def strip_tags(fragment):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', fragment))).strip()


# ---------------------------------------------------------------- input parsing

SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")


def story_url(story_id):
    return f'{SITE}story.php?id={story_id}'


def print_url(story_id):
    return f'{SITE}story_print.php?id={story_id}'


def tag_url(tag_id):
    return f'{SITE}archive.php?list=tag&id={int(tag_id)}'


def classify(line):
    """Return ('story', id), ('list', url) or None for one line of user input."""
    line = line.strip()
    if not line:
        return None
    if '://' not in line and SLUG.match(line):
        return 'story', line
    if '://' not in line and line.startswith(('metabods.com', 'www.metabods.com')):
        line = 'https://' + line
    parsed = urlparse(line)
    if not parsed.netloc.lower().endswith('metabods.com'):
        return None
    query = parse_qs(parsed.query)
    path = parsed.path.rsplit('/', 1)[-1]
    if path in ('story.php', 'story_print.php') and query.get('id') and SLUG.match(query['id'][0]):
        return 'story', query['id'][0]
    if path == 'archive.php' and query.get('list'):
        return 'list', f'{SITE}archive.php?' + parsed.query
    return None


# ---------------------------------------------------------------- list pages

_ROW = re.compile(
    r'<a\s[^>]*href="[^"]*story\.php\?id=([^"&]+)"[^>]*>(.*?)</a>(?:\s|<wbr>|&nbsp;)*'
    r'(?:by\s*<a\s[^>]*list=author&(?:amp;)?id=(\d+)[^>]*>(.*?)</a>)?', re.S | re.I)


def parse_story_rows(page):
    """Stories listed on an archive/author/tag/category page, in page order, de-duplicated."""
    rows = {}
    for m in _ROW.finditer(page):
        title = strip_tags(m.group(2))
        if not title:
            continue
        sid = html.unescape(m.group(1))
        author = strip_tags(m.group(4) or '')
        if sid not in rows:
            rows[sid] = {'id': sid, 'title': title, 'author': author}
        elif author and not rows[sid]['author']:
            rows[sid]['author'] = author
    return list(rows.values())


def parse_page_heading(page):
    m = re.search(r'<title>(.*?)</title>', page, re.S)
    return re.sub(r'\s*-\s*Metabods.*$', '', strip_tags(m.group(1))) if m else ''


def parse_tag_index(page):
    tags = {}
    for m in re.finditer(r'<a\s[^>]*href="[^"]*list=tag&(?:amp;)?id=(\d+)"[^>]*>(.*?)</a>', page, re.S):
        name = strip_tags(m.group(2))
        if name and name.lower() != 'all tags':
            tags.setdefault(int(m.group(1)), name)
    return sorted(tags.items(), key=lambda t: t[1].casefold())


def search_tags(fetcher, tag_ids):
    """Stories carrying each tag; returns {tag_id: [rows]}."""
    return {tid: parse_story_rows(fetcher.get(tag_url(tid))) for tid in tag_ids}


def combine_tag_results(results, match_all):
    """Union or intersection of per-tag story lists, ordered by title."""
    sets = [{r['id'] for r in rows} for rows in results.values()]
    if not sets:
        return []
    keep = set.intersection(*sets) if match_all else set.union(*sets)
    merged = {}
    for rows in results.values():
        for r in rows:
            if r['id'] in keep:
                merged.setdefault(r['id'], r)
    return sorted(merged.values(), key=lambda r: r['title'].casefold())


# ---------------------------------------------------------------- story pages

def parse_story_page(page):
    """Metadata from the normal story page (the print page lacks tags and summary)."""
    info = {'tags': [], 'categories': [], 'summary': ''}
    m = re.search(r'<h5>by\s*<a[^>]*>(.*?)</a>', page, re.S)
    if m:
        info['author'] = strip_tags(m.group(1))
    m = re.search(r'<h5>.*?</h5>\s*<p[^>]*>(.*?)</p>', page, re.S)
    if m:
        text = strip_tags(m.group(1))
        info['summary'] = text
    # The page repeats tags in a per-part popup and a duplicate header; only the first block is the story's own.
    start = page.find('fa-tags me-2')
    if start >= 0:
        end = page.find('fa-tags me-2', start + 12)
        block = page[start:end if end > 0 else start + 60000]
        seen = set()
        for kind, key in (('tag', 'tags'), ('category', 'categories')):
            for m in re.finditer(r'<a\s[^>]*href="/mbxy/site/archive\.php\?list=%s&(?:amp;)?id=\d+"[^>]*>(.*?)</a>' % kind, block, re.S):
                name = strip_tags(m.group(1)).lstrip('\u2022').strip()
                if name and (kind, name) not in seen:
                    seen.add((kind, name))
                    info[key].append(name)
    return info


def parse_print_page(page):
    """Title, author and the ordered (heading, html) sections of story_print.php."""
    m = re.search(r'<h1[^>]*>(.*?)</h1>', page, re.S)
    if not m:
        raise ValueError('Print page has no story title')
    title = strip_tags(m.group(1))
    m = re.search(r'<strong>\s*by\s+(.*?)</strong>', page, re.S)
    author = strip_tags(m.group(1)) if m else 'Unknown'
    m = re.search(r'story copyright\s*&copy;\s*by\s*(.*?)<br', page, re.S)
    copyright_holder = strip_tags(m.group(1)) if m else author
    sections = []
    for chunk in page.split('<div class="xyp_section">')[1:]:
        start = re.search(r'<div[^>]*xyp_section_cols[^>]*>', chunk)
        if not start:
            continue  # title block or footer
        h = re.search(r'<h3[^>]*>(.*?)</h3>', chunk[:start.start()], re.S)
        body = re.sub(r'</div>\s*</div>\s*$', '', chunk[start.end():].rstrip())
        sections.append((strip_tags(h.group(1)) if h else '', body))
    if not sections:
        raise ValueError('Print page has no story text')
    return {'title': title, 'author': author, 'copyright': copyright_holder, 'sections': sections}


def fetch_story(fetcher, story_id):
    """Download one story (all parts) and merge print-page text with story-page metadata."""
    story = parse_print_page(fetcher.get(print_url(story_id)))
    story['id'] = story_id
    story['url'] = story_url(story_id)
    try:
        info = parse_story_page(fetcher.get(story['url']))
    except Cancelled:
        raise
    except IOError:
        info = {'tags': [], 'categories': [], 'summary': ''}
    story.update(tags=info['tags'], categories=info['categories'], summary=info['summary'])
    return story


# ---------------------------------------------------------------- XHTML cleaning

BLOCKS = {'p', 'div', 'blockquote', 'ul', 'ol', 'li', 'hr', 'pre', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
INLINE = {'em', 'strong', 'i', 'b', 'u', 's', 'sub', 'sup', 'span', 'a', 'small', 'big'}
RENAME = {'strike': 's', 'del': 's', 'center': 'div', 'cite': 'em'}
VOID = {'br', 'hr'}
DROP_CONTENT = {'script', 'style', 'head', 'title'}
STYLE_OK = {
    'text-align': re.compile(r'^(left|right|center|justify)$'),
    'margin-left': re.compile(r'^\d+(\.\d+)?(px|em|%)?$'),
    'margin-right': re.compile(r'^\d+(\.\d+)?(px|em|%)?$'),
    'text-indent': re.compile(r'^-?\d+(\.\d+)?(px|em|%)?$'),
    'font-style': re.compile(r'^(italic|normal)$'),
    'font-weight': re.compile(r'^(bold|normal)$'),
    'text-decoration': re.compile(r'^(underline|line-through)$'),
}


def safe_style(value):
    out = []
    for part in (value or '').split(';'):
        if ':' in part:
            key, val = (x.strip().lower() for x in part.split(':', 1))
            if key in STYLE_OK and STYLE_OK[key].match(val):
                out.append(f'{key}:{val}')
    return ';'.join(out)


class Cleaner(HTMLParser):
    """Turns messy site HTML (e.g. nested <p><p>) into well-formed XHTML with a small whitelist."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.stack = []
        self.skip = 0

    def _close_to(self, tag):
        while self.stack:
            top = self.stack.pop()
            self.out.append(f'</{top}>')
            if top == tag:
                break

    def _ensure_paragraph(self):
        if not self.stack:
            self.out.append('<p>')
            self.stack.append('p')

    def handle_starttag(self, tag, attrs):
        tag = RENAME.get(tag, tag)
        attrs = dict(attrs)
        if tag in DROP_CONTENT:
            self.skip += 1
            return
        if tag == 'center':
            attrs['style'] = 'text-align:center'
        if tag in VOID:
            if tag == 'hr':
                self._close_to('p') if 'p' in self.stack else None
            else:
                self._ensure_paragraph()
            self.out.append(f'<{tag}/>')
            return
        if tag in BLOCKS:
            if tag == 'p' or tag in ('div', 'blockquote', 'ul', 'ol', 'pre') or tag.startswith('h'):
                if 'p' in self.stack:
                    self._close_to('p')
            if tag == 'li' and 'li' in self.stack:
                self._close_to('li')
            style = safe_style(attrs.get('style'))
            self.out.append(f'<{tag}' + (f' style={quoteattr(style)}' if style else '') + '>')
            self.stack.append(tag)
        elif tag in INLINE:
            self._ensure_paragraph()
            extra = ''
            if tag == 'a':
                href = attrs.get('href') or ''
                if re.match(r'^https?://', href, re.I):
                    extra = f' href={quoteattr(href)}'
            elif tag == 'span':
                style = safe_style(attrs.get('style'))
                if not style:
                    return
                extra = f' style={quoteattr(style)}'
            self.out.append(f'<{tag}{extra}>')
            self.stack.append(tag)
        # anything else (font, table cells, img...) is unwrapped; its text still flows through

    def handle_endtag(self, tag):
        tag = RENAME.get(tag, tag)
        if tag in DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
        elif tag in self.stack and (tag in BLOCKS or tag in INLINE):
            self._close_to(tag)

    def handle_data(self, data):
        if self.skip:
            return
        if not data.strip() and not self.stack:
            return
        if data.strip():
            self._ensure_paragraph()
        self.out.append(escape(data))

    def result(self):
        self._close_to(None)
        text = ''.join(self.out)
        previous = None
        while previous != text:  # drop paragraphs left empty by the site's nested markup
            previous = text
            text = re.sub(r'<p(?: [^>]*)?>\s*</p>', '', text)
        return text


def clean_fragment(fragment):
    cleaner = Cleaner()
    cleaner.feed(fragment)
    cleaner.close()
    return cleaner.result()


# ---------------------------------------------------------------- EPUB building

CSS = '''body { line-height: 1.4; }
h1, h2, h3 { text-align: center; page-break-after: avoid; }
p { margin: 0 0 0.8em 0; }
.byline, .meta { text-align: center; }
.summary { font-style: italic; text-align: center; }
hr { margin: 1.5em 0; }
'''

XHTML = ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
         '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en">'
         '<head><meta charset="utf-8"/><title>{title}</title><link rel="stylesheet" type="text/css" href="style.css"/></head>'
         '<body>{body}</body></html>')


def _page(title, body):
    return XHTML.format(title=escape(title), body=body)


def chapter_title(heading, story_title, only_one):
    if not heading or only_one and re.match(r'^part\s*\d+\w*$', heading, re.I):
        return story_title
    return heading


def build_epub(stories, title=None, author=None):
    """Return EPUB bytes. One story keeps its parts as chapters; several stories become one omnibus."""
    if not stories:
        raise ValueError('No stories to build')
    combined = len(stories) > 1
    title = title or (stories[0]['title'] if not combined else f"{stories[0]['title']} and {len(stories) - 1} more")
    authors = list(dict.fromkeys(s['author'] for s in stories))
    author = author or ' & '.join(authors)
    tags = list(dict.fromkeys(t for s in stories for t in s.get('tags', []) + s.get('categories', [])))
    summary = stories[0].get('summary', '') if not combined else ''
    book_id = 'urn:uuid:' + str(uuid.uuid5(uuid.NAMESPACE_URL, '|'.join(s['id'] for s in stories)))

    files = []  # (filename, xhtml)
    toc = []    # (label, href, [children])
    title_body = f'<h1>{escape(title)}</h1><p class="byline">by {escape(author)}</p>'
    if summary:
        title_body += f'<p class="summary">{escape(summary)}</p>'
    if combined:
        title_body += '<ol>' + ''.join(f'<li>{escape(s["title"])} — {escape(s["author"])}</li>' for s in stories) + '</ol>'
    else:
        title_body += f'<p class="meta">Source: {escape(stories[0]["url"])}</p>'
    title_body += '<p class="meta">Story copyright remains with the author. Personal copy; not for reposting.</p>'
    files.append(('title.xhtml', _page(title, title_body)))
    toc.append(('Title page', 'title.xhtml', []))

    for si, story in enumerate(stories, 1):
        only_one = len([h for h, _ in story['sections'] if not re.match(r"^author'?s? note", h, re.I)]) <= 1  # a lone part needs no 'Part 1' label
        children = []
        story_href = None
        for pi, (heading, body) in enumerate(story['sections'], 1):
            name = f's{si:03d}_{pi:03d}.xhtml'
            label = chapter_title(heading, story['title'], only_one)
            header = ''
            if combined and pi == 1:
                header = f'<h1>{escape(story["title"])}</h1><p class="byline">by {escape(story["author"])}</p>'
            fragment = clean_fragment(body)
            files.append((name, _page(label, f'{header}<h2>{escape(label)}</h2>{fragment}')))
            story_href = story_href or name
            children.append((label, name, []))
        if combined:
            toc.append((story['title'], story_href, children))
        else:
            toc.extend(children)

    manifest = ''.join(f'<item id="c{i}" href="{n}" media-type="application/xhtml+xml"/>' for i, (n, _) in enumerate(files))
    spine = ''.join(f'<itemref idref="c{i}"/>' for i in range(len(files)))
    subjects = ''.join(f'<dc:subject>{escape(t)}</dc:subject>' for t in tags)
    description = f'<dc:description>{escape(summary)}</dc:description>' if summary else ''
    source = f'<dc:source>{escape(stories[0]["url"])}</dc:source>' if not combined else ''
    opf = ('<?xml version="1.0" encoding="utf-8"?>\n<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           f'<dc:identifier id="bookid">{book_id}</dc:identifier><dc:title>{escape(title)}</dc:title>'
           f'<dc:creator>{escape(author)}</dc:creator><dc:language>en</dc:language><dc:publisher>Metabods</dc:publisher>'
           f'{description}{subjects}{source}'
           f'<meta property="dcterms:modified">{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}</meta></metadata>'
           '<manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
           '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
           f'<item id="css" href="style.css" media-type="text/css"/>{manifest}</manifest>'
           f'<spine toc="ncx">{spine}</spine></package>')

    def nav_list(entries):
        return '<ol>' + ''.join(
            f'<li><a href="{h}">{escape(l)}</a>{nav_list(c) if c else ""}</li>' for l, h, c in entries) + '</ol>'

    nav = _page('Contents', f'<nav epub:type="toc" id="toc"><h1>Contents</h1>{nav_list(toc)}</nav>')
    counter = [0]

    def ncx_points(entries):
        out = []
        for label, href, children in entries:
            counter[0] += 1
            n = counter[0]
            out.append(f'<navPoint id="n{n}" playOrder="{n}"><navLabel><text>{escape(label)}</text></navLabel>'
                       f'<content src="{href}"/>{ncx_points(children)}</navPoint>')
        return ''.join(out)

    ncx = ('<?xml version="1.0" encoding="utf-8"?>\n<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
           f'<head><meta name="dtb:uid" content="{book_id}"/></head><docTitle><text>{escape(title)}</text></docTitle>'
           f'<navMap>{ncx_points(toc)}</navMap></ncx>')
    container = ('<?xml version="1.0"?>\n<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                 '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')

    out = BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr(zipfile.ZipInfo('mimetype'), 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        z.writestr('META-INF/container.xml', container, zipfile.ZIP_DEFLATED)
        z.writestr('OEBPS/content.opf', opf, zipfile.ZIP_DEFLATED)
        z.writestr('OEBPS/nav.xhtml', nav, zipfile.ZIP_DEFLATED)
        z.writestr('OEBPS/toc.ncx', ncx, zipfile.ZIP_DEFLATED)
        z.writestr('OEBPS/style.css', CSS, zipfile.ZIP_DEFLATED)
        for name, content in files:
            z.writestr('OEBPS/' + name, content, zipfile.ZIP_DEFLATED)
    return out.getvalue()


def expand_targets(fetcher, lines, progress=lambda msg: None):
    """Resolve pasted story ids/URLs and list pages (author, tag, category, archive) into story rows."""
    rows, errors = {}, []
    for line in lines:
        kind = classify(line)
        if kind is None:
            if line.strip():
                errors.append(f'Not a Metabods story or list address: {line.strip()}')
            continue
        if kind[0] == 'story':
            rows.setdefault(kind[1], {'id': kind[1], 'title': kind[1], 'author': ''})
            continue
        progress(f'Reading list {kind[1]}')
        try:
            found = parse_story_rows(fetcher.get(kind[1]))
        except IOError as exc:
            errors.append(str(exc))
            continue
        if not found:
            errors.append(f'No stories found at {kind[1]}')
        for row in found:
            rows.setdefault(row['id'], row)
    return list(rows.values()), errors
