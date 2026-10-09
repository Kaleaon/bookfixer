import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
import zipfile
from email.message import Message

spec = importlib.util.spec_from_file_location('engine', Path(__file__).resolve().parents[1] / 'gemini/engine.py')
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


def book(i, **kw):
    base = {'id': i, 'title': f'Book {i}', 'authors': ['A B'], 'series': '', 'series_index': None, 'tags': [], 'languages': [],
            'publisher': '', 'filenames': []}
    base.update(kw)
    return base


def reply(answers):
    return json.dumps({'candidates': [{'content': {'parts': [{'text': json.dumps(answers)}]}, 'finishReason': 'STOP'}]}).encode()


def http_error(code, message='x', retry_after=None):
    headers = Message()
    if retry_after:
        headers['Retry-After'] = retry_after
    return urllib.error.HTTPError('https://x', code, 'err', headers, io.BytesIO(json.dumps({'error': {'message': message}}).encode()))


class Scripted:
    """A transport that returns or raises the next scripted item and records the requests."""

    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, body))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item(body) if callable(item) else item


class SanitizeTests(unittest.TestCase):
    F = engine.FIELDS

    def test_title_and_noop(self):
        b = book(1, title='dune messiah [epub]')
        self.assertEqual(engine.sanitize(b, {'title': ' Dune  Messiah '}, self.F)['title'], ('dune messiah [epub]', 'Dune Messiah'))
        self.assertEqual(engine.sanitize(b, {'title': 'dune messiah [epub]'}, self.F), {})
        self.assertEqual(engine.sanitize(b, {'title': None}, self.F), {})
        self.assertEqual(engine.sanitize(b, {'title': 'x' * 500}, self.F), {})

    def test_only_requested_fields(self):
        self.assertEqual(engine.sanitize(book(1), {'title': 'New'}, ('tags',)), {})

    def test_authors_drop_placeholders_and_dupes(self):
        b = book(1, authors=['Herbert, Frank'])
        got = engine.sanitize(b, {'authors': ['Frank Herbert', 'Frank Herbert', 'Unknown']}, self.F)
        self.assertEqual(got['authors'], (['Herbert, Frank'], ['Frank Herbert']))
        self.assertEqual(engine.sanitize(b, {'authors': ['Unknown']}, self.F), {})
        self.assertEqual(engine.sanitize(b, {'authors': 'Frank'}, self.F), {})

    def test_series_and_index(self):
        b = book(1, title='Dune Messiah (Dune #2)')
        got = engine.sanitize(b, {'series': 'Dune', 'series_index': 2}, self.F)
        self.assertEqual(got['series'], (('', None), ('Dune', 2.0)))
        self.assertEqual(engine.sanitize(b, {'series': 'Dune', 'series_index': 'abc'}, self.F)['series'][1], ('Dune', 1.0))
        self.assertEqual(engine.sanitize(b, {'series': 'Dune', 'series_index': -3}, self.F)['series'][1], ('Dune', 1.0))
        self.assertEqual(engine.sanitize(b, {'series': 'Dune', 'series_index': True}, self.F)['series'][1], ('Dune', 1.0))
        same = book(2, series='Dune', series_index=2.0)
        self.assertEqual(engine.sanitize(same, {'series': 'Dune', 'series_index': 2}, self.F), {})

    def test_tags_add_only_by_default(self):
        b = book(1, tags=['Sci-Fi', 'Keep'])
        got = engine.sanitize(b, {'tags': ['Science Fiction', 'Keep', 'sci-fi']}, self.F)
        self.assertEqual(got['tags'][1], ['Sci-Fi', 'Keep', 'Science Fiction'])
        cleaned = engine.sanitize(b, {'tags': ['Science Fiction', 'Keep']}, self.F, tags_may_be_removed=True)
        self.assertEqual(cleaned['tags'][1], ['Science Fiction', 'Keep'])
        flood = engine.sanitize(book(2), {'tags': [f't{i}' for i in range(30)]}, self.F)
        self.assertEqual(len(flood['tags'][1]), 5)
        self.assertEqual(engine.sanitize(b, {'tags': ['keep', 'SCI-FI']}, self.F), {})

    def test_language_only_when_empty_and_valid(self):
        self.assertEqual(engine.sanitize(book(1), {'language': 'ENG'}, self.F)['language'], ([], ['eng']))
        self.assertEqual(engine.sanitize(book(1, languages=['fra']), {'language': 'eng'}, self.F), {})
        self.assertEqual(engine.sanitize(book(1), {'language': 'English'}, self.F), {})

    def test_big_change_flag(self):
        tidy = {'title': ('the hobbit (retail)', 'The Hobbit')}
        self.assertFalse(engine.is_big_change(tidy))
        self.assertTrue(engine.is_big_change({'title': ('The Hobbit', 'Cooking With Gas')}))
        self.assertFalse(engine.is_big_change({'authors': (['Herbert, Frank'], ['Frank Herbert'])}))
        self.assertTrue(engine.is_big_change({'authors': (['Frank Herbert'], ['Jane Austen'])}))


class NumberedTitleTests(unittest.TestCase):
    def test_pattern(self):
        f = engine.numbering_in_title
        self.assertEqual(f('book 1 - the force awakens'), ('1', 'the force awakens'))
        self.assertEqual(f('Vol. 2: Title'), ('2', 'Title'))
        self.assertEqual(f('Part 3 \u2013 Title'), ('3', 'Title'))
        self.assertEqual(f('#4. Title'), ('4', 'Title'))
        self.assertEqual(f('Book 2.5 - Interlude'), ('2.5', 'Interlude'))
        self.assertIsNone(f('Book of Shadows'))
        self.assertIsNone(f('The Force Awakens'))
        self.assertIsNone(f('Part 3'))

    def test_prompt_carries_the_hint_only_for_numbered_titles(self):
        rows = json.loads(engine.build_prompt([book(1, title='book 1 - the force awakens'), book(2)]).split('\n', 1)[1])
        self.assertEqual(rows[0]['numbering_in_title'], {'volume': 1.0, 'title_without_it': 'the force awakens'})
        self.assertNotIn('numbering_in_title', rows[1])

    def test_numbered_title_is_fixed_end_to_end(self):
        b = book(1, title='book 1 - the force awakens', authors=['Jo Writer'])
        answer = [{'id': 1, 'title': 'The Force Awakens', 'series': 'The Force', 'series_index': 1, 'confidence': 'high', 'reason': 'volume marker'}]
        out, _ = engine.plan_fixes([b], 'k', transport=Scripted(reply(answer)))
        self.assertEqual(out[0]['changes']['title'], ('book 1 - the force awakens', 'The Force Awakens'))
        self.assertEqual(out[0]['changes']['series'][1], ('The Force', 1.0))
        self.assertFalse(out[0]['big'], 'dropping the marker is a tidy-up, not a different book')

    def test_unknown_series_still_fixes_the_title(self):
        b = book(1, title='book 1 - the force awakens')
        out, _ = engine.plan_fixes([b], 'k', transport=Scripted(reply([{'id': 1, 'title': 'The Force Awakens', 'series': None, 'series_index': 1, 'confidence': 'medium'}])))
        self.assertEqual(list(out[0]['changes']), ['title'])

    def test_volume_only_fix_for_a_book_already_in_a_series(self):
        b = book(1, title='book 2 - x', series='Saga', series_index=1.0)
        got = engine.sanitize(b, {'title': 'X', 'series': None, 'series_index': 2}, engine.FIELDS)
        self.assertEqual(got['series'], (('Saga', 1.0), ('Saga', 2.0)))

    def test_same_author_books_share_a_request(self):
        t = Scripted(reply([]), reply([]))
        books = [book(1, authors=['Zed']), book(2, authors=['Amy']), book(3, authors=['Zed']), book(4, authors=['Amy'])]
        engine.plan_fixes(books, 'k', batch_size=2, transport=t)
        first = [r['id'] for r in json.loads(json.loads(t.calls[0][2])['contents'][0]['parts'][0]['text'].split('\n', 1)[1])]
        self.assertEqual(sorted(first), [2, 4])


class ApiTests(unittest.TestCase):
    def test_request_shape_and_key_in_header_only(self):
        t = Scripted(reply([{'id': 1, 'title': 'T', 'confidence': 'high'}]))
        out = engine.generate('SECRET', 'gemini-test', 'prompt', transport=t)
        url, headers, body = t.calls[0]
        self.assertEqual(out[0]['id'], 1)
        self.assertTrue(url.endswith('/models/gemini-test:generateContent'))
        self.assertNotIn('SECRET', url)
        self.assertEqual(headers['x-goog-api-key'], 'SECRET')
        sent = json.loads(body)
        self.assertEqual(sent['generationConfig']['responseMimeType'], 'application/json')
        self.assertEqual(sent['contents'][0]['parts'][0]['text'], 'prompt')

    def test_retries_rate_limit_then_succeeds(self):
        sleeps = []
        t = Scripted(http_error(429, 'slow down', retry_after='7'), http_error(503), reply([]))
        self.assertEqual(engine.generate('k', 'm', 'p', transport=t, sleep=sleeps.append), [])
        self.assertEqual(len(t.calls), 3)
        self.assertEqual(sleeps[0], 7.0)

    def test_gives_up_with_readable_error_without_key(self):
        t = Scripted(*[http_error(429, 'quota')] * 3)
        with self.assertRaises(engine.GeminiError) as cm:
            engine.generate('SECRET', 'm', 'p', transport=t, retries=2, sleep=lambda s: None)
        self.assertIn('limit', str(cm.exception))
        self.assertNotIn('SECRET', str(cm.exception))

    def test_bad_key_message(self):
        with self.assertRaises(engine.GeminiError) as cm:
            engine.generate('k', 'm', 'p', transport=Scripted(http_error(400, 'API key not valid. Please pass a valid API key.')))
        self.assertIn('rejected the API key', str(cm.exception))

    def test_network_failure_and_non_json(self):
        with self.assertRaises(engine.GeminiError) as cm:
            engine.generate('k', 'm', 'p', transport=Scripted(urllib.error.URLError('no route')), retries=0)
        self.assertIn('Could not reach Google', str(cm.exception))
        with self.assertRaises(engine.GeminiError):
            engine.generate('k', 'm', 'p', transport=Scripted(b'<html>'), retries=0)

    def test_blocked_prompt_and_empty_answer(self):
        blocked = json.dumps({'promptFeedback': {'blockReason': 'PROHIBITED_CONTENT'}}).encode()
        with self.assertRaises(engine.Blocked):
            engine.generate('k', 'm', 'p', transport=Scripted(blocked))
        safety = json.dumps({'candidates': [{'finishReason': 'SAFETY'}]}).encode()
        with self.assertRaises(engine.Blocked):
            engine.generate('k', 'm', 'p', transport=Scripted(safety))

    def test_truncated_json_is_reported(self):
        cut = json.dumps({'candidates': [{'content': {'parts': [{'text': '[{"id": 1, "tit'}]}}]}).encode()
        with self.assertRaises(engine.GeminiError) as cm:
            engine.generate('k', 'm', 'p', transport=Scripted(cut))
        self.assertIn('smaller batch', str(cm.exception))

    def test_list_models_filters_and_pages(self):
        page1 = json.dumps({'models': [{'name': 'models/gemini-b', 'supportedGenerationMethods': ['generateContent']},
                                       {'name': 'models/embed', 'supportedGenerationMethods': ['embedContent']}], 'nextPageToken': 'n'}).encode()
        page2 = json.dumps({'models': [{'name': 'models/gemini-a', 'supportedGenerationMethods': ['generateContent']}]}).encode()
        t = Scripted(page1, page2)
        self.assertEqual(engine.list_models('k', transport=t), ['gemini-a', 'gemini-b'])
        self.assertIn('pageToken=n', t.calls[1][0])


class PlanTests(unittest.TestCase):
    def test_plan_filters_confidence_noops_and_foreign_ids(self):
        books = [book(1, title='dune [epub]'), book(2, title='Fine'), book(3, title='x file'), book(4, title='Unsure')]
        answers = [{'id': 1, 'title': 'Dune', 'confidence': 'high', 'reason': 'junk'},
                   {'id': 2, 'title': 'Fine', 'confidence': 'high'},
                   {'id': 3, 'title': 'X', 'confidence': 'medium'},
                   {'id': 99, 'title': 'Injected', 'confidence': 'high'},
                   {'id': 4, 'title': 'Other', 'confidence': 'low'}]
        out, skipped = engine.plan_fixes(books, 'k', transport=Scripted(reply(answers)))
        self.assertEqual([s['id'] for s in out], [1, 3])
        self.assertEqual(out[0]['changes']['title'], ('dune [epub]', 'Dune'))
        self.assertEqual(skipped, [])

    def test_missing_answers_are_reported(self):
        out, skipped = engine.plan_fixes([book(1), book(2)], 'k', transport=Scripted(reply([{'id': 1, 'title': 'New', 'confidence': 'high'}])))
        self.assertEqual(len(out), 1)
        self.assertEqual(skipped, ['Book 2: no answer from the model'])

    def test_batches_are_sized(self):
        t = Scripted(reply([]), reply([]), reply([]))
        engine.plan_fixes([book(i) for i in range(5)], 'k', batch_size=2, transport=t)
        self.assertEqual(len(t.calls), 3)

    def test_blocked_batch_is_split_to_find_the_book(self):
        blocked = json.dumps({'promptFeedback': {'blockReason': 'SAFETY'}}).encode()

        def by_body(body):
            ids = [row['id'] for row in json.loads(json.loads(body)['contents'][0]['parts'][0]['text'].split('\n', 1)[1])]
            return blocked if 3 in ids else reply([{'id': i, 'title': f'T{i}', 'confidence': 'high'} for i in ids])

        t = Scripted(*[by_body] * 10)
        out, skipped = engine.plan_fixes([book(i) for i in (1, 2, 3, 4)], 'k', transport=t)
        self.assertEqual(sorted(s['id'] for s in out), [1, 2, 4])
        self.assertEqual(len(skipped), 1)
        self.assertTrue(skipped[0].startswith('Book 3:'))

    def test_cancel_returns_partial_results(self):
        flags = iter([False, False, True, True, True])
        out, skipped = engine.plan_fixes([book(1), book(2)], 'k', batch_size=1, cancelled=lambda: next(flags),
                                         transport=Scripted(reply([{'id': 1, 'title': 'One', 'confidence': 'high'}]), reply([])))
        self.assertEqual([s['id'] for s in out], [1])

    def test_bad_key_stops_the_whole_run(self):
        with self.assertRaises(engine.GeminiError):
            engine.plan_fixes([book(1)], 'k', transport=Scripted(http_error(403, 'API key not valid')))


class InputTests(unittest.TestCase):
    def test_prompt_contains_book_fields_and_excerpt(self):
        text = engine.build_prompt([book(7, title='T', filenames=['T - A.epub'], excerpt='Once upon')])
        rows = json.loads(text.split('\n', 1)[1])
        self.assertEqual((rows[0]['id'], rows[0]['file_names'], rows[0]['opening_text']), (7, ['T - A.epub'], 'Once upon'))
        self.assertNotIn('opening_text', json.loads(engine.build_prompt([book(1)]).split('\n', 1)[1])[0])

    def test_epub_excerpt_skips_short_pages_and_bad_files(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'b.epub'
            long_text = 'Word ' * 400
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('a_title.xhtml', '<html><body><p>Title</p></body></html>')
                z.writestr('b_ch1.xhtml', f'<html><head><title>no</title></head><body><script>bad()</script><p>{long_text}</p></body></html>')
            got = engine.epub_excerpt(path, limit=100)
            self.assertEqual(len(got), 100)
            self.assertTrue(got.startswith('Word Word'))
            self.assertNotIn('bad()', got)
            (Path(d) / 'junk.epub').write_bytes(b'not a zip')
            self.assertEqual(engine.epub_excerpt(Path(d) / 'junk.epub'), '')
            self.assertEqual(engine.epub_excerpt(Path(d) / 'missing.epub'), '')


if __name__ == '__main__':
    unittest.main()
