"""Nifty archive parsing and download logic. Pure standard library so it can be tested outside Calibre."""
import html
import re
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

try:  # inside Calibre the shared module ships in the plugin package
    from .storykit import Cancelled, Fetcher, build_epub as _build_epub, clean_fragment, escape, strip_tags  # noqa: F401
except ImportError:  # tests load this file directly with common/ on sys.path
    from storykit import Cancelled, Fetcher, build_epub as _build_epub, clean_fragment, escape, strip_tags  # noqa: F401

SITE = 'https://www.nifty.org/nifty/'
PUBLISHER = 'Nifty'
SECTIONS = ['gay', 'lesbian', 'bisexual', 'transgender']
MAX_DEPTH = 6


def build_epub(stories, title=None, author=None):
    return _build_epub(stories, title=title, author=author, publisher=PUBLISHER)


# ---------------------------------------------------------------- addresses

def humanize(slug):
    return re.sub(r'[-_]+', ' ', slug).strip().title()


def classify(line):
    """Return the archive path (relative to /nifty/, trailing slash = directory) or None."""
    line = line.strip()
    if not line:
        return None
    if '://' not in line and line.startswith(('nifty.org', 'www.nifty.org')):
        line = 'https://' + line
    parsed = urlparse(line)
    host = parsed.netloc.lower()
    if not (host == 'nifty.org' or host.endswith('.nifty.org')) or not parsed.path.startswith('/nifty/'):
        return None
    path = parsed.path[len('/nifty/'):]
    if not path or '..' in path.split('/'):
        return None
    if path.endswith(('.html', '.xml', '.txt')) and '/' not in path:
        return None  # site pages such as new.html or authorslist.html
    return path


def url_for(path):
    return SITE + path


# ---------------------------------------------------------------- listings

_ROW = re.compile(
    r'<(?:td|div)[^>]*>\s*(Dir|[\d.]+[KMG]?)\s*</(?:td|div)>\s*<(?:td|div)[^>]*>\s*([^<]*?)\s*</(?:td|div)>\s*'
    r'<(?:td|div)[^>]*>\s*<a\s+href="([^"#?/][^"]*)"', re.I)


def parse_listing(page):
    """Entries of a directory page as dicts: name, is_dir, size, date. Newest first, as the site orders them."""
    entries = []
    for m in _ROW.finditer(page):
        name = html.unescape(m.group(3))
        if name.startswith(('.', '..')):
            continue
        is_dir = m.group(1).lower() == 'dir' or name.endswith('/')
        entries.append({'name': name.rstrip('/'), 'is_dir': is_dir, 'size': m.group(1), 'date': m.group(2)})
    return entries


def parse_categories(page, section):
    """Category directories linked from a section page, in page order."""
    seen = []
    for m in re.finditer(r'href="/nifty/%s/([^/"#?]+)/"' % re.escape(section), page):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


GENERIC_PREFIXES = {'chapter', 'chap', 'ch', 'part', 'pt', 'story', 'book', 'episode', 'ep', 'p', 'c'}


def strip_ext(name):
    return re.sub(r'(?i)\.(?:html?|txt)$', '', name)


def book_title(prefix, folder):
    """Display name for a file group; generic names such as 'chapter' borrow the folder's name."""
    return humanize(folder if prefix.lower() in GENERIC_PREFIXES and folder else prefix)


def split_chapter(name):
    m = re.match(r'^(.*?)[-_]?(\d+)$', strip_ext(name))
    if m and m.group(1):
        return m.group(1), int(m.group(2))
    return strip_ext(name), None


def group_files(entries):
    """Group chapter files (slug-1, slug-2, ...) into books. Returns [(prefix, [names in reading order])]."""
    groups = {}
    for e in entries:
        if e['is_dir']:
            continue
        prefix, number = split_chapter(e['name'])
        groups.setdefault(prefix, []).append((-1 if number is None else number, e['name']))
    return [(prefix, [n for _, n in sorted(items)]) for prefix, items in groups.items()]


def expand_dir(fetcher, path):
    """Story references found in a directory: file groups, plus unresolved sub-folders."""
    path = path.rstrip('/')
    entries = parse_listing(fetcher.get(url_for(path + '/')))
    refs = []
    for e in entries:
        if e['is_dir']:
            refs.append({'id': f"{path}/{e['name']}", 'title': humanize(e['name']), 'author': '', 'date': e['date'],
                         'dir': f"{path}/{e['name']}", 'files': None, 'detail': 'series folder'})
    dates = {e['name']: e['date'] for e in entries}
    for prefix, names in group_files(entries):
        refs.append({'id': f'{path}/{prefix}', 'title': book_title(prefix, path.rsplit('/', 1)[-1]), 'author': '', 'date': dates[names[-1]],
                     'dir': None, 'files': [f'{path}/{n}' for n in names],
                     'detail': f'{len(names)} chapter(s)' if len(names) > 1 else 'single story'})
    return refs


def resolve_ref(fetcher, ref, depth=0):
    """Turn an unresolved folder reference into file-group references (one level of sub-folders deep per call)."""
    if ref['files'] is not None:
        return [ref]
    if depth >= MAX_DEPTH:
        return []
    out = []
    for sub in expand_dir(fetcher, ref['dir']):
        out.extend(resolve_ref(fetcher, sub, depth + 1))
    return out


def expand_targets(fetcher, lines, progress=lambda msg: None):
    """Resolve pasted Nifty addresses into story references (files, series folders or category contents)."""
    refs, errors = {}, []
    for line in lines:
        path = classify(line)
        if path is None:
            if line.strip():
                errors.append(f'Not a Nifty story or folder address: {line.strip()}')
            continue
        parts = path.strip('/').split('/')
        try:
            if len(parts) == 1:
                errors.append(f'{line.strip()}: a whole section is too broad; pick a category or story.')
            elif len(parts) == 2:
                progress(f'Reading category {path}')
                found = expand_dir(fetcher, path)
                if not found:
                    errors.append(f'No stories found at {line.strip()}')
                for r in found:
                    refs.setdefault(r['id'], r)
            elif path.endswith('/'):
                refs.setdefault(path.rstrip('/'), {'id': path.rstrip('/'), 'title': humanize(parts[-1]), 'author': '',
                                                   'date': '', 'dir': path.rstrip('/'), 'files': None, 'detail': 'series folder'})
            else:
                folder, name = path.rsplit('/', 1)
                prefix, number = split_chapter(name)
                if number is None:
                    r = {'id': path, 'title': humanize(prefix), 'author': '', 'date': '', 'dir': None, 'files': [path], 'detail': 'single story'}
                else:  # a chapter link means the whole series
                    progress(f'Reading series {folder}')
                    names = dict(group_files(parse_listing(fetcher.get(url_for(folder + '/'))))).get(prefix) or [name]
                    r = {'id': f'{folder}/{prefix}', 'title': book_title(prefix, folder.rsplit('/', 1)[-1]), 'author': '', 'date': '', 'dir': None,
                         'files': [f'{folder}/{n}' for n in names], 'detail': f'{len(names)} chapter(s)'}
                refs.setdefault(r['id'], r)
        except IOError as exc:
            errors.append(str(exc))
    return list(refs.values()), errors


# ---------------------------------------------------------------- chapter text

HEADER = re.compile(r'^([A-Za-z][A-Za-z\-]*):[ \t]*(.*)$')
RULE = re.compile(r'^\s*(?:[_\-=~#*]\s*){3,}$')  # scene breaks: ____, ***, * * *, ---
EMAIL = re.compile(r'<[^<>@\s]+@[^<>\s]+>|\([^()@\s]+@[^()\s]+\)|\S+@\S+')


def split_headers(text):
    """Separate the mail-style header block (Date/From/Subject...) from the body."""
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    headers, i = {}, 0
    while i < len(lines) and lines[i].strip():
        m = HEADER.match(lines[i])
        if m:
            headers[m.group(1).lower()] = m.group(2).strip()
        elif not (lines[i][:1] in ' \t' and headers):
            return {}, '\n'.join(lines)  # not a header block
        i += 1
    if not headers.keys() & {'from', 'subject', 'date'}:
        return {}, '\n'.join(lines)
    return headers, '\n'.join(lines[i:]).strip('\n')


def author_name(value):
    name = EMAIL.sub('', value or '').strip(' \t"\'<>()')
    if name:
        return re.sub(r'\s+', ' ', name)
    m = re.match(r'\s*<?([^@<\s]+)@', value or '')
    return m.group(1) if m else 'Unknown'


def looks_like_html(text):
    return bool(re.search(r'<\s*(?:html|body|p|br|div)\b', text[:4000], re.I))


def html_body(text):
    m = re.search(r'<body[^>]*>(.*)</body>', text, re.S | re.I) or re.search(r'<body[^>]*>(.*)', text, re.S | re.I)
    return clean_fragment(m.group(1) if m else text)


def html_title(text):
    m = re.search(r'<title[^>]*>(.*?)</title>', text, re.S | re.I)
    return strip_tags(m.group(1)) if m else ''


def text_to_html(text):
    """Unwrap hard-wrapped plain text into paragraphs; keep verse-like blocks and rules."""
    out = []
    for block in re.split(r'\n\s*\n', text.replace('\t', '    ').strip('\n')):
        lines = [ln.rstrip() for ln in block.split('\n') if ln.strip()]
        if not lines:
            continue
        if all(RULE.match(ln) for ln in lines):
            out.append('<hr/>')
        elif len(lines) >= 3 and sum(len(ln.strip()) for ln in lines) / len(lines) < 45:
            out.append('<p>' + '<br/>'.join(escape(ln.strip()) for ln in lines) + '</p>')  # poems, lists, signatures
        else:
            out.append('<p>' + escape(' '.join(ln.strip() for ln in lines)) + '</p>')
    return ''.join(out)


NUMBER_WORDS = 'one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve'


def clean_title(subject, fallback):
    """Strip chapter markers, category lists and truncated trailers from a Subject: line."""
    title = re.sub(r'(?i)[\s,:;\-\u2013(]*\b(?:chapter|chap|ch|part|pt|p|book|episode|ep)(?=[\s.\d])\.?\s*'
                   r'(?:\d+|[IVXLC]+\b|(?:%s)\b).*$' % NUMBER_WORDS, '', subject or '')
    title = re.sub(r'\s*\([^()]*$', '', title)                    # truncated "(Lesbian/Domination, oral"
    title = re.sub(r'\s*\([^()]*[/,][^()]*\)\s*$', '', title)    # "(Gay/Adult/College)" category list
    title = re.sub(r'[\s#:;,\-]*\d+\s*$', '', title).strip(' \t:;,-')
    return title or fallback


def fetch_book(fetcher, ref, progress=lambda msg: None):
    """Download every chapter file of a resolved reference and return one story dict."""
    paths = ref['files']
    chapters, first_headers = [], {}
    for n, path in enumerate(paths, 1):
        progress(f"{ref['title']}: chapter {n} of {len(paths)}")
        raw = fetcher.get(url_for(path))
        if looks_like_html(raw):  # a few old files are HTML pages rather than mail-style text
            headers, converted = {'subject': html_title(raw)}, html_body(raw)
        else:
            headers, body = split_headers(raw)
            converted = text_to_html(body)
        if n == 1:
            first_headers = headers
        number = split_chapter(path.rsplit('/', 1)[-1])[1]
        label = '' if len(paths) == 1 else f'Chapter {number if number is not None else n}'
        chapters.append((label, converted or '<p>(empty)</p>'))
    folder_parts = ref['id'].split('/')
    tags = [humanize(p) for p in folder_parts[:-1]][:2]  # section and category
    pubdate = ''
    try:
        pubdate = parsedate_to_datetime(first_headers.get('date', '')).date().isoformat()
    except (TypeError, ValueError, IndexError):
        pass
    return {'id': ref['id'], 'url': url_for(paths[0]) if len(paths) == 1 else url_for(paths[0].rsplit('/', 1)[0] + '/'),
            'title': clean_title(first_headers.get('subject', ''), ref['title']),
            'author': author_name(first_headers.get('from', '')), 'sections': chapters,
            'tags': tags, 'categories': [], 'summary': '', 'publisher': PUBLISHER, 'pubdate': pubdate}


def download_ref(fetcher, ref, skip_ids=frozenset(), progress=lambda msg: None):
    """Resolve a reference and download its books. Returns (stories, skipped_count)."""
    stories, skipped = [], 0
    for resolved in resolve_ref(fetcher, ref):
        if resolved['id'] in skip_ids:
            skipped += 1
            continue
        stories.append(fetch_book(fetcher, resolved, progress))
    return stories, skipped
