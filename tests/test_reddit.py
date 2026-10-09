import html
import http.server
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import xml.dom.minidom
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reddit_samples import entry, feed, md  # noqa: E402
spec = importlib.util.spec_from_file_location('rcore', Path(__file__).resolve().parents[1] / 'reddit/core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


class SourceTests(unittest.TestCase):
    def test_subreddit_user_and_search_forms(self):
        for text in ('r/HFY', '/r/hfy/', 'https://www.reddit.com/r/HFY/new', 'old.reddit.com/r/HFY', 'https://www.reddit.com/r/HFY/.rss'):
            self.assertEqual(core.parse_source(text)['kind'], 'subreddit', text)
        self.assertEqual(core.parse_source('u/Some_Author')['user'], 'Some_Author')
        self.assertEqual(core.parse_source('https://www.reddit.com/user/Some_Author/submitted/')['kind'], 'user')
        s = core.parse_source('https://www.reddit.com/r/HFY/search/?q=Out+of+Cruel+Space&restrict_sr=1')
        self.assertEqual((s['kind'], s['subreddit'], s['query']), ('search', 'HFY', 'Out of Cruel Space'))
        self.assertEqual(core.parse_source('https://www.reddit.com/search/?q=cruel')['subreddit'], '')

    def test_source_text_round_trips(self):
        for text in ('r/HFY', 'u/Some_Author', 'https://www.reddit.com/r/HFY/search/?q=Out+of+Cruel+Space&restrict_sr=1',
                     'https://www.reddit.com/search/?q=weird+%26+words'):
            src = core.parse_source(text)
            self.assertEqual(core.parse_source(core.source_text(src)), src, text)

    def test_bad_input(self):
        for text in ('', 'hello world', 'https://example.com/r/HFY', 'https://www.reddit.com/r/HFY/comments/abc123/title/',
                     'https://www.reddit.com/r/HFY/search?restrict_sr=1', 'r/'):
            with self.assertRaises(core.SourceError, msg=text):
                core.parse_source(text)

    def test_addresses_are_built_and_encoded(self):
        sub = core.parse_source('r/HFY')
        self.assertEqual(core.feed_url(sub, 25), 'https://www.reddit.com/r/HFY/new.rss?limit=25')
        self.assertIn('after=t3_abc', core.feed_url(sub, 100, 't3_abc'))
        user = core.parse_source('u/name')
        self.assertTrue(core.feed_url(user).startswith('https://www.reddit.com/user/name/submitted.rss?sort=new'))
        found = core.parse_source('https://www.reddit.com/r/HFY/search/?q=Out+of+Cruel+Space&restrict_sr=1')
        url = core.feed_url(found)
        self.assertIn('/r/HFY/search.rss?', url)
        self.assertIn('q=Out%20of%20Cruel%20Space', url)
        self.assertIn('restrict_sr=on', url)
        self.assertIn('type=link', core.api_path(found))
        self.assertIn('raw_json=1', core.api_path(sub))
        self.assertEqual(core.describe_source(found), 'search “Out of Cruel Space” in r/HFY')


class CleaningTests(unittest.TestCase):
    def test_wrapper_and_footer_are_removed(self):
        out = core.main_html(md('<p>The ship <em>shook</em>.</p>').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&'))
        self.assertEqual(out, '<p>The ship <em>shook</em>.</p>')
        self.assertNotIn('submitted', out)

    def test_escaped_api_html_is_understood(self):
        self.assertEqual(core.main_html('&lt;!-- SC_OFF --&gt;&lt;div class="md"&gt;&lt;p&gt;Hello&lt;/p&gt;&lt;/div&gt;&lt;!-- SC_ON --&gt;'), '<p>Hello</p>')
        self.assertEqual(core.main_html('<!-- SC_OFF --><div class="md"><p>Hello</p></div><!-- SC_ON -->'), '<p>Hello</p>')

    def test_navigation_lines_go_but_story_text_stays(self):
        body = ('<p><a href="https://x.org/a">First</a> | <a href="https://x.org/b">Previous</a> | <a href="https://x.org/c">Next</a></p>'
                '<p>Story text with a <a href="https://x.org/d">next</a> step.</p><p>More story.</p><hr/>'
                '<p><a href="https://x.org/a">First</a> | <a href="https://x.org/b">Previous</a></p>')
        out = core.strip_navigation(core.clean_fragment(body))
        self.assertEqual(out, '<p>Story text with a <a href="https://x.org/d">next</a> step.</p><p>More story.</p>')
        self.assertEqual(core.strip_navigation('<p>Only text.</p>'), '<p>Only text.</p>')
        self.assertEqual(core.strip_navigation('<p>Next</p>'), '', 'a post that is only a navigation line has no story left')
        self.assertEqual(core.strip_navigation('<p>Next chapter is where it gets good.</p>'), '<p>Next chapter is where it gets good.</p>')


class ParsingTests(unittest.TestCase):
    def test_atom_entries(self):
        xml_text = feed(entry('aaa111', 'Out of Cruel Space (Chapter 2)', '<p>Two.</p>', stamp='2026-10-08T12:00:00+00:00'),
                        entry('bbb222', 'A picture', None), entry('ccc333', 'Comment', '<p>x</p>', kind='t1'),
                        entry('ddd444', 'Out of Cruel Space (Chapter 1)', '<p>One &amp; more.</p>', author='/u/Writer', stamp='2026-10-07T12:00:00+00:00'))
        entries, after = core.parse_atom(xml_text)
        self.assertEqual([e['id'] for e in entries], ['t3_aaa111', 't3_bbb222', 't3_ddd444'], 'comments are skipped')
        self.assertEqual(after, 't3_ddd444', 'the oldest id is the token for the next page')
        first = entries[0]
        self.assertEqual((first['title'], first['author'], first['html'], first['subreddit']),
                         ('Out of Cruel Space (Chapter 2)', 'someone', '<p>Two.</p>', 'HFY'))
        self.assertEqual(entries[2]['author'], 'Writer')
        self.assertEqual(entries[2]['html'], '<p>One &amp; more.</p>')
        self.assertEqual(entries[1]['html'], '', 'a picture post has no story text')
        self.assertGreater(first['created'], entries[2]['created'])
        self.assertTrue(first['link'].endswith('/comments/aaa111/slug/'))

    def test_atom_that_is_not_xml_is_reported(self):
        for text in ('', '<html>403 Forbidden</html', 'Too Many Requests'):
            with self.assertRaises(ValueError):
                core.parse_atom(text)
        self.assertEqual(core.parse_atom(feed()), ([], None))

    def test_api_listing(self):
        data = {'kind': 'Listing', 'data': {'after': 't3_next', 'children': [
            {'kind': 't3', 'data': {'name': 't3_aaa', 'title': 'Chapter &amp; One', 'author': 'Writer', 'created_utc': 1790000000.0,
                                    'permalink': '/r/HFY/comments/aaa/x/', 'subreddit': 'HFY', 'is_self': True,
                                    'selftext_html': '<!-- SC_OFF --><div class="md"><p>Body.</p></div><!-- SC_ON -->'}},
            {'kind': 't3', 'data': {'name': 't3_bbb', 'title': 'Link post', 'author': 'Writer', 'created_utc': 1.0, 'permalink': '/r/HFY/comments/bbb/x/', 'selftext_html': None}},
            {'kind': 't1', 'data': {'name': 't1_ccc'}}]}}
        entries, after = core.parse_listing(json.dumps(data))
        self.assertEqual(after, 't3_next')
        self.assertEqual([e['id'] for e in entries], ['t3_aaa', 't3_bbb'])
        self.assertEqual((entries[0]['title'], entries[0]['html'], entries[0]['link']), ('Chapter & One', '<p>Body.</p>', 'https://www.reddit.com/r/HFY/comments/aaa/x/'))
        self.assertEqual(entries[1]['html'], '')


class FilterTests(unittest.TestCase):
    def post(self, title='Out of Cruel Space (Chapter 3)', author='Writer', html='<p>x</p>'):
        return {'id': 't3_a', 'title': title, 'author': author, 'html': html}

    def test_filters(self):
        f = lambda **kw: dict({'title_filter': '', 'author_filter': ''}, **kw)
        self.assertTrue(core.matches(self.post(), f()))
        self.assertTrue(core.matches(self.post(), f(title_filter='cruel SPACE')))
        self.assertFalse(core.matches(self.post(), f(title_filter='something else')))
        self.assertTrue(core.matches(self.post(), f(title_filter=r're:chapter\s+\d+')))
        self.assertFalse(core.matches(self.post(), f(title_filter='re:((')), 'a broken regex matches nothing rather than everything')
        self.assertTrue(core.matches(self.post(), f(author_filter='writer')))
        self.assertFalse(core.matches(self.post(), f(author_filter='other')))
        self.assertFalse(core.matches(self.post(html=''), f()), 'posts without story text never match')

    def test_new_follow_cleans_input(self):
        follow = core.new_follow('  Out of Cruel Space ', 'https://www.reddit.com/r/HFY/search/?q=Out+of+Cruel+Space&restrict_sr=1', ' (Chapter ', '/u/Writer')
        self.assertEqual((follow['name'], follow['title_filter'], follow['author_filter']), ('Out of Cruel Space', '(Chapter', 'Writer'))
        self.assertEqual(len(follow['id']), 10)
        self.assertEqual(core.new_follow('', 'u/name')['name'], 'u/name')


class FakeSource:
    """Pages of canned posts, newest first, like a feed."""
    mode = 'rss'

    def __init__(self, posts, per_page=2, fail_on_page=None):
        self.posts, self.per_page, self.fail_on_page = posts, per_page, fail_on_page
        self.calls = []

    def page(self, src, after=None, limit=100):
        self.calls.append(after)
        if self.fail_on_page is not None and len(self.calls) == self.fail_on_page:
            raise core.RateLimited('https://www.reddit.com/x', 90)
        ids = [p['id'] for p in self.posts]
        start = ids.index(after) + 1 if after else 0
        chunk = self.posts[start:start + self.per_page]
        return chunk, (chunk[-1]['id'] if chunk and start + self.per_page < len(self.posts) else None)


def post(n, title=None, html=None, author='Writer'):
    return {'id': f't3_{n:03d}', 'title': title or f'Out of Cruel Space (Chapter {n})', 'author': author, 'created': 1790000000.0 + n * 86400,
            'link': f'https://www.reddit.com/r/HFY/comments/{n:03d}/x/', 'html': html if html is not None else f'<p>Chapter {n} text.</p>', 'subreddit': 'HFY'}


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.follow = core.new_follow('Out of Cruel Space', 'https://www.reddit.com/r/HFY/search/?q=Out+of+Cruel+Space&restrict_sr=1', 'Out of Cruel Space')

    def tearDown(self):
        self.tmp.cleanup()

    def cache(self):
        return core.ChapterCache(self.tmp.name, self.follow['id'])

    def feed_posts(self, upto, noise=()):
        posts = [post(n) for n in range(upto, 0, -1)]  # newest first
        for n in noise:
            posts.insert(1, post(900 + n, title=f'Unrelated story {n}'))
        return posts

    def test_first_check_reads_back_through_the_feed(self):
        source = FakeSource(self.feed_posts(5, noise=(1, 2)))
        cache = self.cache()
        result = core.check_follow(source, self.follow, cache)
        self.assertEqual(len(result['new']), 5)
        self.assertEqual(len(cache.posts), 5, 'unrelated posts are not kept')
        self.assertEqual(result['pages'], 4, 'every page was read until the feed ended')
        self.assertEqual([p['title'][-3:-1] for p in cache.ordered()], ['r 1', 'r 2', 'r 3', 'r 4', 'r 5'][:0] or [p['title'][-3:-1] for p in cache.ordered()])
        self.assertEqual(cache.ordered()[0]['title'], 'Out of Cruel Space (Chapter 1)', 'oldest first')
        self.assertTrue(Path(cache.path).exists())

    def test_later_check_stops_at_what_it_has_seen_and_finds_only_new_posts(self):
        core.check_follow(FakeSource(self.feed_posts(5)), self.follow, self.cache())
        source = FakeSource(self.feed_posts(7), per_page=2)
        cache = self.cache()  # reloaded from disk
        self.assertEqual(len(cache.posts), 5)
        result = core.check_follow(source, self.follow, cache)
        self.assertEqual(sorted(result['new']), ['Out of Cruel Space (Chapter 6)', 'Out of Cruel Space (Chapter 7)'])
        self.assertLessEqual(result['pages'], 2, 'it must not page through the whole history again')
        self.assertEqual(len(cache.posts), 7)
        quiet = core.check_follow(FakeSource(self.feed_posts(7)), self.follow, self.cache())
        self.assertEqual((quiet['new'], quiet['changed']), ([], []))

    def test_an_edited_post_is_noticed(self):
        core.check_follow(FakeSource(self.feed_posts(3)), self.follow, self.cache())
        posts = self.feed_posts(3)
        posts[0] = post(3, html='<p>Chapter 3 text, corrected.</p>')
        cache = self.cache()
        result = core.check_follow(FakeSource(posts), self.follow, cache)
        self.assertEqual((result['new'], result['changed']), ([], ['Out of Cruel Space (Chapter 3)']))
        self.assertIn('corrected', cache.posts['t3_003']['html'])

    def test_a_rate_limit_keeps_what_was_read_and_propagates(self):
        source = FakeSource(self.feed_posts(8), per_page=2, fail_on_page=3)
        cache = self.cache()
        with self.assertRaises(core.RateLimited) as caught:
            core.check_follow(source, self.follow, cache)
        self.assertEqual(caught.exception.retry_after, 90)
        self.assertEqual(len(self.cache().posts), 4, 'two pages were read and saved before the limit')

    def test_cancel_stops_before_the_next_page(self):
        calls = []
        source = FakeSource(self.feed_posts(8), per_page=2)
        with self.assertRaises(core.Cancelled):
            core.check_follow(source, self.follow, self.cache(), cancelled=lambda: len(source.calls) >= 1)
        self.assertEqual(len(source.calls), 1)
        self.assertEqual(calls, [])

    def test_a_damaged_cache_is_rebuilt(self):
        cache = self.cache()
        Path(cache.path).write_text('{not json')
        result = core.check_follow(FakeSource(self.feed_posts(2)), self.follow, self.cache())
        self.assertEqual(len(result['new']), 2)

    def test_book_is_built_oldest_first_with_chapters(self):
        cache = self.cache()
        core.check_follow(FakeSource(self.feed_posts(4)), self.follow, cache)
        story = core.build_story(self.follow, cache)
        self.assertEqual((story['title'], story['author'], len(story['sections'])), ('Out of Cruel Space', 'Writer', 4))
        self.assertEqual([h for h, _ in story['sections']][0], 'Out of Cruel Space (Chapter 1)')
        self.assertIn('4 chapters collected from Reddit', story['summary'])
        self.assertEqual(story['tags'], ['Reddit', 'r/HFY'])
        data = core.build_epub(story)
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertIsNone(z.testzip())
        for name in z.namelist():
            if name.endswith(('.xhtml', '.opf', '.ncx', '.xml')):
                xml.dom.minidom.parseString(z.read(name))
        self.assertIn('<dc:publisher>Reddit</dc:publisher>', z.read('OEBPS/content.opf').decode())
        with self.assertRaises(ValueError):
            core.build_story(self.follow, core.ChapterCache(self.tmp.name, 'empty'))


class RunFollowsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.a = core.new_follow('Series A', 'u/alice', 'Chapter')
        self.b = core.new_follow('Series B', 'u/bob', 'Chapter')
        self.c = core.new_follow('Series C', 'u/carol', 'Chapter')

    def tearDown(self):
        self.tmp.cleanup()

    class BySource:
        """Feeds keyed by the followed user; can raise per user."""
        mode = 'rss'

        def __init__(self, feeds, raises=None):
            self.feeds, self.raises, self.asked = feeds, raises or {}, []

        def page(self, src, after=None, limit=100):
            self.asked.append(src['user'])
            if src['user'] in self.raises:
                raise self.raises[src['user']]
            return self.feeds[src['user']], None

    def test_due_respects_the_interval_and_never_polls_faster_than_the_minimum(self):
        follow = {'last_checked': 1000.0}
        self.assertFalse(core.due(follow, 6, now=1000.0 + 5 * 3600))
        self.assertTrue(core.due(follow, 6, now=1000.0 + 6 * 3600))
        self.assertTrue(core.due({}, 6, now=5000.0), 'never checked is always due')
        self.assertFalse(core.due(follow, 0.01, now=1000.0 + 1800), 'asking for a tiny interval still waits the minimum hour')

    def test_each_follow_is_checked_and_stamped(self):
        source = self.BySource({'alice': [post(1, 'Chapter 1')], 'bob': [post(2, 'Chapter 9', author='bob')], 'carol': []})
        results = core.run_follows(source, [self.a, self.b, self.c], self.tmp.name, now=lambda: 4242.0)
        self.assertEqual([r['new'] for r in results], [['Chapter 1'], ['Chapter 9'], []])
        self.assertEqual(self.a['last_checked'], 4242.0)
        self.assertEqual(self.a['last_status'], '1 new chapter(s)')
        self.assertEqual(self.c['last_status'], 'up to date')

    def test_an_error_in_one_follow_does_not_stop_the_others(self):
        source = self.BySource({'alice': [post(1, 'Chapter 1')], 'carol': [post(3, 'Chapter 3', author='carol')]},
                               raises={'bob': IOError('Could not fetch: HTTP 404')})
        results = core.run_follows(source, [self.a, self.b, self.c], self.tmp.name)
        self.assertEqual([bool(r['error']) for r in results], [False, True, False])
        self.assertIn('404', self.b['last_status'])
        self.assertEqual(results[2]['new'], ['Chapter 3'])

    def test_a_rate_limit_ends_the_run_and_skips_the_rest(self):
        source = self.BySource({'alice': [post(1, 'Chapter 1')]}, raises={'bob': core.RateLimited('u', 120)})
        results = core.run_follows(source, [self.a, self.b, self.c], self.tmp.name)
        self.assertEqual([r['skipped'] for r in results], [False, False, True])
        self.assertTrue(results[1]['rate_limited'])
        self.assertEqual(results[1]['retry_after'], 120)
        self.assertEqual(source.asked, ['alice', 'bob'], 'carol was never requested after the limit')
        self.assertEqual(self.c.get('last_checked'), 0.0, 'a skipped follow is not marked as checked')
        self.assertIn('slow down', self.b['last_status'])
        self.assertEqual(self.a['last_status'], '1 new chapter(s)', 'work done before the limit stands')


class FakeResponse(io.BytesIO):
    headers = type('H', (), {'get': lambda self, k, d=None: d, 'get_content_charset': lambda self: 'utf-8'})()
    __enter__ = lambda self: self
    __exit__ = lambda self, *a: False


class SpacingTests(unittest.TestCase):
    def test_requests_without_credentials_stay_under_ten_a_minute(self):
        self.assertGreaterEqual(core.MIN_FEED_INTERVAL, 6.0)
        self.assertGreaterEqual(core.MIN_API_INTERVAL, 1.0)
        self.assertGreaterEqual(core.MIN_CHECK_HOURS, 1.0)


class FeedSourceTests(unittest.TestCase):
    def test_feed_requests_are_polite_and_parsed(self):
        seen = []

        def opener(req, timeout):
            seen.append((req.full_url, dict(req.header_items())))
            return FakeResponse(feed(entry('aaa111', 'Chapter 1', '<p>One.</p>')).encode())

        source = core.FeedSource(core.Fetcher(min_interval=0, opener=opener))
        entries, after = source.page(core.parse_source('r/HFY'))
        self.assertEqual([e['id'] for e in entries], ['t3_aaa111'])
        url, headers = seen[0]
        self.assertTrue(url.startswith('https://www.reddit.com/r/HFY/new.rss'))
        self.assertIn('CalibreRedditFollower', headers['User-agent'], 'an honest, identifying user agent')
        self.assertNotIn('Authorization', headers)

    def test_429_is_not_retried(self):
        calls = []

        def opener(req, timeout):
            calls.append(1)
            raise urllib.error.HTTPError(req.full_url, 429, 'Too Many Requests', {'Retry-After': '60'}, None)

        with self.assertRaises(core.RateLimited):
            core.FeedSource(core.Fetcher(min_interval=0, opener=opener)).page(core.parse_source('r/HFY'))
        self.assertEqual(len(calls), 1)


class FakeReddit(http.server.BaseHTTPRequestHandler):
    log = []
    mode = 'ok'

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length'])).decode()
        type(self).log.append(('token', dict(self.headers), body))
        reply = {'error': 'unauthorized_client'} if type(self).mode == 'badcreds' else {'access_token': 'tok123', 'expires_in': 3600, 'token_type': 'bearer'}
        self._send(200, reply)

    def do_GET(self):
        type(self).log.append(('get', dict(self.headers), self.path))
        if type(self).mode == 'limited':
            self.send_response(429); self.send_header('Retry-After', '45'); self.end_headers(); return
        self._send(200, {'kind': 'Listing', 'data': {'after': None, 'children': [{'kind': 't3', 'data': {
            'name': 't3_aaa', 'title': 'Chapter 1', 'author': 'Writer', 'created_utc': 1790000000.0, 'permalink': '/r/HFY/comments/aaa/x/',
            'selftext_html': '<!-- SC_OFF --><div class="md"><p>Hi.</p></div><!-- SC_ON -->'}}]}})

    def _send(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json'); self.end_headers(); self.wfile.write(data)


class ApiSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), FakeReddit)
        cls.base = f'http://127.0.0.1:{cls.server.server_address[1]}'
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeReddit.log, FakeReddit.mode = [], 'ok'

    def api(self, secret='', client='abc123'):
        return core.ApiSource(core.Fetcher(min_interval=0), client, secret, 'Reader', token_url=self.base + '/token', base=self.base)

    def test_installed_app_flow_and_listing(self):
        entries, after = self.api().page(core.parse_source('r/HFY'))
        self.assertEqual([(e['id'], e['html']) for e in entries], [('t3_aaa', '<p>Hi.</p>')])
        token_call, get_call = FakeReddit.log
        self.assertIn('installed_client', token_call[2])
        self.assertIn('device_id=', token_call[2])
        self.assertTrue(token_call[1]['Authorization'].startswith('Basic '))
        self.assertEqual(get_call[1]['Authorization'], 'bearer tok123')
        self.assertEqual(get_call[1]['User-Agent'], 'calibre:reddit-follower:1.0 (by /u/Reader)')
        self.assertIn('/r/HFY/new?', get_call[2])
        self.assertIn('raw_json=1', get_call[2])

    def test_secret_uses_client_credentials_and_token_is_reused(self):
        api = self.api(secret='s3cret')
        api.page(core.parse_source('u/name'))
        api.page(core.parse_source('u/name'))
        tokens = [c for c in FakeReddit.log if c[0] == 'token']
        self.assertEqual(len(tokens), 1, 'one token serves later pages')
        self.assertIn('grant_type=client_credentials', tokens[0][2])

    def test_bad_credentials_and_missing_client_id(self):
        FakeReddit.mode = 'badcreds'
        with self.assertRaisesRegex(IOError, 'refused the credentials'):
            self.api().page(core.parse_source('r/HFY'))
        with self.assertRaises(core.SourceError):
            self.api(client='').page(core.parse_source('r/HFY'))

    def test_rate_limit_from_the_api(self):
        FakeReddit.mode = 'limited'
        with self.assertRaises(core.RateLimited) as caught:
            self.api().page(core.parse_source('r/HFY'))
        self.assertEqual(caught.exception.retry_after, 45)


if __name__ == '__main__':
    unittest.main()
