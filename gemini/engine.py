"""Asks the Google Gemini API to suggest fixes for book metadata, and checks the answers. Pure standard library so it can be
tested outside Calibre.

Nothing here changes a library. plan_fixes() returns suggestions; the caller shows them and applies only what the user accepts.
The model is told to leave anything it is unsure about alone, and every answer is validated again here before it is offered.
"""
import difflib
import json
import re
import time
import urllib.error
import urllib.request
import zipfile
from html.parser import HTMLParser

API_ROOT = 'https://generativelanguage.googleapis.com/v1beta'
DEFAULT_MODEL = 'gemini-2.5-flash'
CONFIDENCE = {'low': 0, 'medium': 1, 'high': 2}
FIELDS = ('title', 'authors', 'series', 'tags', 'language')
RETRY_STATUS = {429, 500, 502, 503, 504}
# A new title this unlike the old one is flagged as a big change and left unticked in the preview.
BIG_CHANGE_RATIO = 0.5

INSTRUCTIONS = '''You clean up the metadata of ebooks in a personal Calibre library. You get a JSON list of books; for each you may suggest corrections.

Rules:
- Fix only what is clearly wrong: junk in titles (site names, "z-lib", "[epub]", "(retail)", file extensions, underscores or dots used as spaces, ALL CAPS or all lower case), authors written "Last, First" or joined into one string, authors that are really a website or "Unknown", series and volume number that are visible in the title or file name but missing from the series fields, and obviously mis-spelled or duplicate tags.
- Use proper title case for English titles, and keep the author's real spelling. Authors must be listed as "First Last".
- Titles that start with a volume marker, such as "book 1 - the force awakens", "Vol. 2: Title", "Part 3 - Title" or "#4. Title", must lose that marker: the title becomes just the real title in title case ("The Force Awakens") and the number goes in series_index. Books that carry a "numbering_in_title" hint have exactly this problem. Set series too when you know it from the author, from other books in the list, or from the title; if you do not know the series name, return series null and still fix the title and series_index.
- A series name must not contain the volume number, and the volume goes in series_index (for example title "Dune Messiah (Dune #2)" gives title "Dune Messiah", series "Dune", series_index 2).
- Tags: return the complete cleaned tag list for the book (keep good tags, merge duplicates such as "sci-fi" and "Science Fiction" into one form, fix case). You may add at most 5 well-known genre tags you are certain of. Do not invent plot details.
- language: only when the book has none; an ISO 639-2 three-letter code such as "eng".
- Never invent facts. If you are not sure, return null for that field, which means "leave it as it is". Returning a field identical to the current value is the same as null.
- confidence says how sure you are about your suggestions for that book: high only when the correction is obvious from the data given.
- reason is one short sentence.
- Return one object for every book id you were given, in the same order.'''

RESPONSE_SCHEMA = {
    'type': 'ARRAY',
    'items': {
        'type': 'OBJECT',
        'properties': {
            'id': {'type': 'INTEGER'},
            'title': {'type': 'STRING', 'nullable': True},
            'authors': {'type': 'ARRAY', 'items': {'type': 'STRING'}, 'nullable': True},
            'series': {'type': 'STRING', 'nullable': True},
            'series_index': {'type': 'NUMBER', 'nullable': True},
            'tags': {'type': 'ARRAY', 'items': {'type': 'STRING'}, 'nullable': True},
            'language': {'type': 'STRING', 'nullable': True},
            'confidence': {'type': 'STRING', 'enum': ['low', 'medium', 'high']},
            'reason': {'type': 'STRING'},
        },
        'required': ['id', 'confidence'],
    },
}


class GeminiError(Exception):
    """A problem talking to the API that the user should read. Never contains the API key."""


class Blocked(GeminiError):
    """Google's safety filter refused the request (common for adult fiction)."""


# ---------------------------------------------------------------------------------------------------------------- API

def _post(url, headers, body, timeout):
    request = urllib.request.Request(url, data=body, headers=headers, method='POST')
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _get(url, headers, timeout):
    request = urllib.request.Request(url, headers=headers, method='GET')
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _error_message(exc):
    try:
        data = json.loads(exc.read().decode('utf-8', 'replace'))
        return data['error']['message']
    except Exception:
        return exc.reason if isinstance(exc.reason, str) else f'HTTP {exc.code}'


def _request(method, url, api_key, body=None, retries=4, timeout=120, transport=None, sleep=time.sleep, cancelled=lambda: False):
    """One API call with the retry rules: rate limits and server errors are retried with a growing pause."""
    headers = {'x-goog-api-key': api_key, 'Content-Type': 'application/json', 'User-Agent': 'calibre-gemini-library-fixer'}
    send = transport or ((lambda u, h, b, t: _post(u, h, b, t)) if method == 'POST' else (lambda u, h, b, t: _get(u, h, t)))
    delay = 3.0
    for attempt in range(retries + 1):
        if cancelled():
            raise GeminiError('Cancelled')
        try:
            return json.loads(send(url, headers, body, timeout).decode('utf-8'))
        except urllib.error.HTTPError as exc:
            message = _error_message(exc)
            if exc.code in RETRY_STATUS and attempt < retries:
                try:
                    wait = min(float(exc.headers.get('Retry-After')), 120)
                except (TypeError, ValueError, AttributeError):
                    wait = delay
                sleep(wait)
                delay *= 2
                continue
            if exc.code in (400, 403) and 'API key' in message:
                raise GeminiError('Google rejected the API key. Check that it is copied completely and that the Gemini API is enabled for it.') from None
            if exc.code == 429:
                raise GeminiError(f'Google says the request limit is used up: {message}') from None
            raise GeminiError(f'Google returned an error ({exc.code}): {message}') from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            if attempt < retries:
                sleep(delay)
                delay *= 2
                continue
            reason = getattr(exc, 'reason', exc)
            raise GeminiError(f'Could not reach Google: {reason}') from None
        except ValueError:
            raise GeminiError('Google sent an answer that is not JSON.') from None
    raise GeminiError('Google did not answer.')


def generate(api_key, model, prompt, **kw):
    """Asks the model for JSON that matches RESPONSE_SCHEMA and returns the parsed list."""
    body = json.dumps({
        'systemInstruction': {'parts': [{'text': INSTRUCTIONS}]},
        'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
        'generationConfig': {'temperature': 0.1, 'responseMimeType': 'application/json', 'responseSchema': RESPONSE_SCHEMA},
    }).encode('utf-8')
    data = _request('POST', f'{API_ROOT}/models/{model}:generateContent', api_key, body, **kw)
    feedback = data.get('promptFeedback') or {}
    if feedback.get('blockReason'):
        raise Blocked(f"Google's safety filter blocked the request ({feedback['blockReason']}).")
    candidates = data.get('candidates') or []
    if not candidates:
        raise Blocked('Google returned no answer for this request.')
    candidate = candidates[0]
    text = ''.join(p.get('text', '') for p in (candidate.get('content') or {}).get('parts', []))
    if not text.strip():
        if candidate.get('finishReason') in ('SAFETY', 'PROHIBITED_CONTENT', 'BLOCKLIST', 'RECITATION'):
            raise Blocked(f"Google's safety filter blocked the answer ({candidate['finishReason']}).")
        raise GeminiError(f"Google returned an empty answer (finish reason: {candidate.get('finishReason', 'unknown')}).")
    try:
        result = json.loads(text)
    except ValueError:
        raise GeminiError('The model\'s answer was not valid JSON (it may have been cut off). Try a smaller batch size.') from None
    if not isinstance(result, list):
        raise GeminiError('The model\'s answer was not a list.')
    return result


def list_models(api_key, **kw):
    """Names of models that can generate content, such as 'gemini-2.5-flash'."""
    names = []
    token = ''
    while True:
        data = _request('GET', f'{API_ROOT}/models?pageSize=100' + (f'&pageToken={token}' if token else ''), api_key, **kw)
        for m in data.get('models', []):
            if 'generateContent' in m.get('supportedGenerationMethods', []):
                names.append(m['name'].split('/', 1)[-1])
        token = data.get('nextPageToken')
        if not token:
            return sorted(names)


# ------------------------------------------------------------------------------------------------------------- input

class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        self.skip += tag in ('script', 'style', 'head')

    def handle_endtag(self, tag):
        self.skip -= tag in ('script', 'style', 'head') and self.skip > 0

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def epub_excerpt(path, limit=1500):
    """The first readable text of an EPUB (skipping very short front-matter pages), or ''. Never raises."""
    try:
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(('.xhtml', '.html', '.htm'))]
            names.sort()
            for name in names:
                parser = _Text()
                parser.feed(z.read(name).decode('utf-8', 'replace'))
                text = re.sub(r'\s+', ' ', ' '.join(parser.parts)).strip()
                if len(text) > 400:
                    return text[:limit]
    except Exception:
        pass
    return ''


NUMBERED = re.compile(r'^\s*(?:book|bk\.?|vol(?:ume)?\.?|part|#)\s*(\d+(?:\.\d+)?)\s*[-:\u2013\u2014.]\s*(\S.*)$', re.I)


def numbering_in_title(title):
    """('1', 'the force awakens') for "book 1 - the force awakens"; None when the title has no leading volume marker."""
    m = NUMBERED.match(title or '')
    return (m.group(1), m.group(2).strip()) if m else None


def build_prompt(books):
    """books: dicts with id, title, authors, series, series_index, tags, languages, publisher, filenames and optional excerpt."""
    rows = []
    for b in books:
        row = {'id': b['id'], 'title': b.get('title') or '', 'authors': list(b.get('authors') or []),
               'series': b.get('series') or '', 'series_index': b.get('series_index'), 'tags': list(b.get('tags') or []),
               'language': ', '.join(b.get('languages') or []), 'publisher': b.get('publisher') or '',
               'file_names': list(b.get('filenames') or [])}
        found = numbering_in_title(b.get('title'))
        if found:
            row['numbering_in_title'] = {'volume': float(found[0]), 'title_without_it': found[1]}
        if b.get('excerpt'):
            row['opening_text'] = b['excerpt']
        rows.append(row)
    return 'Books to check:\n' + json.dumps(rows, ensure_ascii=False, indent=1)


# ------------------------------------------------------------------------------------------------------- validation

def _clean(text, limit):
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    return text if 0 < len(text) <= limit else ''


def _same_ci(a, b):
    return re.sub(r'\W+', '', a).lower() == re.sub(r'\W+', '', b).lower()


def sanitize(book, raw, fields, tags_may_be_removed=False):
    """Turns one raw model answer into {field: (old, new)} for a real, safe change. Anything doubtful is dropped."""
    changes = {}
    if 'title' in fields:
        new = _clean(raw.get('title'), 300)
        if new and new != book.get('title'):
            changes['title'] = (book.get('title') or '', new)
    if 'authors' in fields and isinstance(raw.get('authors'), list):
        new = list(dict.fromkeys(a for a in (_clean(x, 100) for x in raw['authors']) if a))[:10]
        old = list(book.get('authors') or [])
        # "Unknown" is Calibre's placeholder; never write it back as an author name.
        new = [a for a in new if a.lower() not in ('unknown', 'n/a', 'none')]
        if new and new != old:
            changes['authors'] = (old, new)
    if 'series' in fields:
        series = _clean(raw.get('series'), 200)
        index = raw.get('series_index')
        try:
            index = float(index) if index is not None and not isinstance(index, bool) else None
        except (TypeError, ValueError):
            index = None
        if index is not None and not 0 <= index <= 10000:
            index = None
        if not series and book.get('series') and index is not None and index != book.get('series_index'):
            series = book['series']  # the book already has a series; only the volume number is being fixed
        if series and (series != book.get('series') or (index is not None and index != book.get('series_index'))):
            old_index = book.get('series_index') if book.get('series') else None
            changes['series'] = ((book.get('series') or '', old_index),
                                 (series, index if index is not None else book.get('series_index') or 1.0))
    if 'tags' in fields and isinstance(raw.get('tags'), list):
        old = list(book.get('tags') or [])
        proposed = list(dict.fromkeys(t for t in (_clean(x, 60) for x in raw['tags']) if t))[:40]
        have = {t.lower() for t in old}
        if tags_may_be_removed:
            new = proposed
        else:
            new = old + [t for t in proposed if t.lower() not in have][:5]
        if new and sorted(new) != sorted(old):
            changes['tags'] = (old, new)
    if 'language' in fields and not book.get('languages'):
        code = str(raw.get('language') or '').strip().lower()
        if re.fullmatch(r'[a-z]{3}', code):
            changes['language'] = ([], [code])
    return changes


def is_big_change(changes):
    """True when a title or author change looks like a different book rather than a tidy-up."""
    if 'title' in changes:
        old, new = changes['title']
        if difflib.SequenceMatcher(None, re.sub(r'\W+', ' ', old).lower().strip(), re.sub(r'\W+', ' ', new).lower().strip()).ratio() < BIG_CHANGE_RATIO:
            return True
    if 'authors' in changes:
        old, new = changes['authors']
        if old and not any(_same_ci(o, n) or set(re.findall(r'\w+', o.lower())) & set(re.findall(r'\w+', n.lower())) for o in old for n in new):
            return True
    return False


# ------------------------------------------------------------------------------------------------------------- driver

def plan_fixes(books, api_key, model=DEFAULT_MODEL, fields=FIELDS, min_confidence='medium', batch_size=15,
               tags_may_be_removed=False, progress=lambda text: None, cancelled=lambda: False, **kw):
    """Returns (suggestions, skipped). A suggestion is {'id', 'title', 'changes', 'confidence', 'reason', 'big'}; skipped is a
    list of 'title: why' strings for books that could not be checked. On cancel, returns what was finished so far."""
    suggestions, skipped = [], []
    threshold = CONFIDENCE.get(min_confidence, 1)
    by_id = {b['id']: b for b in books}

    def ask(batch):
        try:
            answers = generate(api_key, model, build_prompt(batch), cancelled=cancelled, **kw)
        except Blocked as exc:
            if len(batch) == 1:
                skipped.append(f"{batch[0].get('title') or batch[0]['id']}: {exc}")
                return
            half = len(batch) // 2  # find the book that trips the filter instead of losing the whole batch
            ask(batch[:half])
            ask(batch[half:])
            return
        wanted = {b['id'] for b in batch}
        seen = set()
        for raw in answers:
            if not isinstance(raw, dict) or raw.get('id') not in wanted or raw['id'] in seen:
                continue  # an id we did not ask about, or a repeat, is ignored
            seen.add(raw['id'])
            book = by_id[raw['id']]
            confidence = str(raw.get('confidence') or 'low').lower()
            changes = sanitize(book, raw, fields, tags_may_be_removed)
            if changes and CONFIDENCE.get(confidence, 0) >= threshold:
                suggestions.append({'id': book['id'], 'title': book.get('title') or '', 'changes': changes, 'confidence': confidence,
                                    'reason': _clean(raw.get('reason'), 300), 'big': is_big_change(changes)})
        for missing in wanted - seen:
            skipped.append(f"{by_id[missing].get('title') or missing}: no answer from the model")

    size = max(1, int(batch_size))
    # Books by the same author go in the same request, so volumes of one series can be recognised together.
    books = sorted(books, key=lambda b: ((b.get('authors') or [''])[0].lower(), (b.get('series') or '').lower(), (b.get('title') or '').lower()))
    for start in range(0, len(books), size):
        if cancelled():
            break
        progress(f'Asking Gemini… {min(start + size, len(books))} of {len(books)} books')
        try:
            ask(books[start:start + size])
        except GeminiError as exc:
            if str(exc) == 'Cancelled':
                break
            raise
    return suggestions, skipped
