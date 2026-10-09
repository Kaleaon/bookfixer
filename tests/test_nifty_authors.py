import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
spec = importlib.util.spec_from_file_location('ncore', Path(__file__).resolve().parents[1] / 'nifty/core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


def panel(anchor, name, *entries):
    lis = '\n'.join(f'<li><a href="{href}">{title}</a>' for href, title in entries)
    return (f'<div id="{anchor}" class="panel panel-default"><div class="panel-heading"><h4 class="panel-title">{name}</h4></div>'
            f'<div class="panel-body"><ul>\n{lis}\n</ul></div></div>')


AUTHORS_PAGE = (panel('writer', 'Writer &amp; Co',
                      ('/nifty/gay/college/texas-tails/', 'Texas Tails'),
                      ('/nifty/gay/highschool/jeremiah', 'Texas Tails: Jeremiah'),
                      ('/nifty/gay/college/other-one.html', 'Other &amp; One'),
                      ('/nifty/gay/college/other-one', 'Other &amp; One'),
                      ('/nifty/lesbian/beginnings/elsewhere', 'Elsewhere'))
                + panel('solo', 'Solo Author', ('/nifty/gay/camping/lone-wolf', 'Lone Wolf')))
PROLIFIC_PAGE = panel('writer', 'Writer &amp; Co', ('/nifty/gay/college/texas-tails/', 'Texas Tails'),
                      ('/nifty/gay/sf-fantasy/third-story', 'A Third Story'))


def stories(*pairs):
    return [{'title': t, 'path': p, 'dir': False} for t, p in pairs]


class FakeFetcher:
    def __init__(self, pages):
        self.pages, self.requested = pages, []

    def get(self, url):
        self.requested.append(url)
        if url not in self.pages:
            raise IOError('missing ' + url)
        return self.pages[url]


class AuthorsDirectoryTests(unittest.TestCase):
    def test_paths_are_normalised_and_duplicates_dropped(self):
        authors = core.parse_authors(AUTHORS_PAGE)
        self.assertEqual([a['name'] for a in authors], ['Writer & Co', 'Solo Author'])
        writer = authors[0]['stories']
        self.assertEqual([s['path'] for s in writer],
                         ['gay/college/texas-tails', 'gay/highschool/jeremiah', 'gay/college/other-one', 'lesbian/beginnings/elsewhere'])
        self.assertTrue(writer[0]['dir'])
        self.assertFalse(writer[1]['dir'])
        self.assertEqual(writer[2]['title'], 'Other & One')
        self.assertEqual(core.author_sections(authors[0]), ['gay', 'lesbian'])

    def test_both_pages_merge_without_repeating_stories(self):
        f = FakeFetcher({core.SITE + 'authors.html': AUTHORS_PAGE, core.SITE + 'prolific.html': PROLIFIC_PAGE})
        authors = core.load_authors(f)
        writer = next(a for a in authors if a['id'] == 'writer')
        paths = [s['path'] for s in writer['stories']]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertIn('gay/sf-fantasy/third-story', paths)
        self.assertEqual([a['name'] for a in authors], ['Solo Author', 'Writer & Co'], 'sorted by name')

    def test_norm_path(self):
        for href in ('/nifty/gay/x/y', '/nifty/gay/x/y/', '/nifty/gay/x/y.html', '/nifty/gay/x/y.htm#top'):
            self.assertEqual(core.norm_path(href), 'gay/x/y')


class SeriesSuggestionTests(unittest.TestCase):
    def names(self, series):
        return {e['name']: [s['title'] for s in e['stories']] for e in series}

    def test_colon_numbered_and_extension_sets_across_folders(self):
        series, rest = core.suggest_series(stories(
            ('Texas Tails', 'gay/young-friends/texas-tails'), ('Texas Tails: Roy and John', 'gay/highschool/roy-and-john'),
            ('Texas Tails: Jeremiah', 'gay/highschool/jeremiah'),
            ('The Beau Cycle 8', 'gay/incest/the-beau-cycle-8'), ('The Beau Cycle 6', 'gay/highschool/the-beau-cycle-6'),
            ('The Beau Cycle 7', 'gay/highschool/the-beau-cycle-7'),
            ('Valley Boys', 'gay/beginnings/valley-boys'), ('Valley Boys Rugby Tour', 'gay/athletics/valley-boys-rugby-tour'),
            ('Pornman II', 'gay/a/pornman-ii'), ('Pornman III', 'gay/a/pornman-iii'), ('Pornman 4', 'gay/a/pornman-4'),
            ('Unrelated Story', 'gay/college/unrelated')))
        by_name = self.names(series)
        self.assertEqual(by_name['Texas Tails'], ['Texas Tails', 'Texas Tails: Jeremiah', 'Texas Tails: Roy and John'])
        self.assertEqual(by_name['The Beau Cycle'], ['The Beau Cycle 6', 'The Beau Cycle 7', 'The Beau Cycle 8'], 'ordered by number')
        self.assertEqual(by_name['Valley Boys'], ['Valley Boys', 'Valley Boys Rugby Tour'])
        self.assertEqual(len(by_name['Pornman']), 3)
        self.assertEqual([s['title'] for s in rest], ['Unrelated Story'])

    def test_author_habits_are_not_series(self):
        series, rest = core.suggest_series(stories(
            ('Night with Mark', 'gay/a/night-with-mark'), ('Night with Mike', 'gay/b/night-with-mike'),
            ('Sex with Corey', 'gay/a/sex-with-corey'), ('Sex with My Uncle', 'gay/b/sex-with-my-uncle'),
            ('Call Me Gangsta', 'gay/a/call-me-gangsta'), ('Call Me Paxton', 'gay/b/call-me-paxton')))
        self.assertEqual(series, [])
        self.assertEqual(len(rest), 6)

    def test_alternate_versions_are_not_a_series(self):
        series, _ = core.suggest_series(stories(
            ('Bed Buddies', 'gay/a/bed-buddies'), ('Bed Buddies (Revised)', 'gay/b/bed-buddies-revised'),
            ('The Only Boy On Calisto', 'gay/a/calisto'), ('The Only Boy On Calisto [Original]', 'gay/b/calisto-original'),
            ("Lost in Ireland's Rural Village", 'gay/a/lost'), ("Lost in Ireland's Rural Village (redux)", 'gay/b/lost-redux')))
        self.assertEqual(series, [])

    def test_short_or_generic_names_do_not_form_sets(self):
        series, _ = core.suggest_series(stories(('Dad', 'gay/a/dad'), ('Dad: Part 2', 'gay/b/dad-2'), ('The Boys', 'gay/a/boys'),
                                                ('The Boys Next Door', 'gay/b/boys-next-door')))
        self.assertEqual(series, [])

    def test_empty_and_single(self):
        self.assertEqual(core.suggest_series([]), ([], []))
        series, rest = core.suggest_series(stories(('Only One', 'gay/a/one')))
        self.assertEqual((series, len(rest)), ([], 1))


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.a = {'title': 'Series One', 'path': 'gay/a/series-one', 'dir': True}
        self.b = {'title': 'Series Two', 'path': 'gay/b/series-two', 'dir': False}
        self.c = {'title': 'Alone', 'path': 'gay/c/alone', 'dir': False}

    def test_story_address(self):
        self.assertEqual(core.story_address(self.a), core.SITE + 'gay/a/series-one/')
        self.assertEqual(core.story_address(self.b), core.SITE + 'gay/b/series-two')

    def test_sets_combine_and_singles_stay_single(self):
        sel = core.build_selection([('Series', [self.a, self.b])], [self.c])
        self.assertEqual([i['title'] for i in sel], ['Series', None])
        self.assertEqual(len(sel[0]['addresses']), 2)

    def test_one_ticked_story_of_a_set_is_just_a_story(self):
        sel = core.build_selection([('Series', [self.a])], [])
        self.assertEqual(sel, [{'title': None, 'addresses': [core.story_address(self.a)]}])

    def test_combining_can_be_switched_off(self):
        sel = core.build_selection([('Series', [self.a, self.b])], [], combine_series=False)
        self.assertEqual([i['title'] for i in sel], [None, None])

    def test_combine_everything_into_one_titled_book(self):
        sel = core.build_selection([('Series', [self.a, self.b])], [self.c], combine_all_title='  My Collection ')
        self.assertEqual(len(sel), 1)
        self.assertEqual((sel[0]['title'], len(sel[0]['addresses'])), ('My Collection', 3))
        self.assertEqual(core.build_selection([], [], combine_all_title='Empty'), [])


CHAPTER = 'Date: Thu, 1 Oct 2026 11:00:00 +0000\nFrom: Writer <w@example.com>\nSubject: {subject}\n\nSome text for {subject}.\n'


class DownloadSelectionTests(unittest.TestCase):
    def pages(self):
        return {
            core.SITE + 'gay/college/texas-tails/': ('<table><tr><td>3K</td><td>Oct 3 1999</td><td><a href="texas-tails-1">texas-tails-1</a></td></tr>'
                                                      '<tr><td>3K</td><td>Oct 4 1999</td><td><a href="texas-tails-2">texas-tails-2</a></td></tr></table>'),
            core.SITE + 'gay/college/texas-tails/texas-tails-1': CHAPTER.format(subject='Texas Tails Chapter 1'),
            core.SITE + 'gay/college/texas-tails/texas-tails-2': CHAPTER.format(subject='Texas Tails Chapter 2'),
            core.SITE + 'gay/highschool/jeremiah': CHAPTER.format(subject='Texas Tails: Jeremiah'),
        }

    def selection(self):
        tt = {'title': 'Texas Tails', 'path': 'gay/college/texas-tails', 'dir': True}
        jer = {'title': 'Texas Tails: Jeremiah', 'path': 'gay/highschool/jeremiah', 'dir': False}
        return core.build_selection([('Texas Tails', [tt, jer])], [])

    def test_a_set_from_two_folders_becomes_one_group_of_stories(self):
        groups, skipped, problems = core.download_selection(FakeFetcher(self.pages()), self.selection())
        self.assertEqual((skipped, problems), (0, []))
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['title'], 'Texas Tails')
        self.assertEqual([s['title'] for s in groups[0]['stories']], ['Texas Tails', 'Texas Tails: Jeremiah'])
        self.assertEqual(len(groups[0]['stories'][0]['sections']), 2, 'the multi-chapter story keeps its chapters')
        data = core.build_epub(groups[0]['stories'], title=groups[0]['title'])
        self.assertTrue(data.startswith(b'PK'))

    def test_already_owned_stories_are_skipped(self):
        groups, skipped, _ = core.download_selection(FakeFetcher(self.pages()), self.selection(), skip_ids={'gay/highschool/jeremiah'})
        self.assertEqual(skipped, 1)
        self.assertEqual([s['title'] for s in groups[0]['stories']], ['Texas Tails'])

    def test_a_missing_page_is_reported_and_the_rest_continues(self):
        pages = self.pages()
        del pages[core.SITE + 'gay/highschool/jeremiah']
        groups, _, problems = core.download_selection(FakeFetcher(pages), self.selection())
        self.assertEqual(len(groups[0]['stories']), 1)
        self.assertTrue(any('jeremiah' in p for p in problems), problems)

    def test_finished_groups_survive_a_cancel(self):
        class Cancelling(FakeFetcher):
            def get(self, url):
                if url.endswith('/jeremiah'):
                    raise core.Cancelled()
                return super().get(url)
        done = []
        selection = core.build_selection([], [{'title': 'Texas Tails', 'path': 'gay/college/texas-tails', 'dir': True},
                                              {'title': 'Texas Tails: Jeremiah', 'path': 'gay/highschool/jeremiah', 'dir': False}])
        with self.assertRaises(core.Cancelled):
            for group in core.iter_selection(Cancelling(self.pages()), selection):
                done.append(group)
        self.assertEqual(len(done), 1, 'the first story finished before the cancel and must be kept')


if __name__ == '__main__':
    unittest.main()
