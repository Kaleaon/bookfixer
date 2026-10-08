"""Runs the real dialogs under real Qt (PyQt6, offscreen) with canned site pages. Skipped when PyQt6 is not installed.

Calibre itself is replaced by small stubs (its preferences store and plain modules); everything else, including Qt's
behaviour, is real. This is what caught the 'finished task looks cancelled' bug that left the tag search empty.
"""
import builtins
import importlib
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import MagicMock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PyQt6 import QtCore, QtWidgets
    HAVE_QT = True
except ImportError:  # also raised when system libraries such as libEGL are missing
    HAVE_QT = False
import build_plugins  # noqa: E402

TAG_INDEX = ('<p class="xy23R-sectionheaders">A</p>'
             '<a href="?list=tag&id=1">Alpha</a><a href="?list=tag&id=2">Beta</a><a href="?list=tag&id=90">All Tags</a>')


def story_row(sid, title, author='Writer'):
    return (f'<p class="xy23R-story-row-graf"><a href="/mbxy/site/story.php?id={sid}">{title}</a> by '
            f'<a href="/mbxy/site/archive.php?list=author&id=7">{author}</a></p>')


TAG_PAGES = {
    '1': story_row('one', 'Story One') + story_row('two', 'Story Two'),
    '2': story_row('two', 'Story Two') + story_row('three', 'Story Three'),
}


class StubPrefs(dict):
    def __init__(self):
        super().__init__()
        self.defaults = {}

    def __getitem__(self, key):
        try:
            return dict.__getitem__(self, key)
        except KeyError:
            return self.defaults[key]


class FakeFetcher:
    """Stands in for the site: serves the tag index and per-tag story lists."""

    def __init__(self, min_interval=0, cancelled=lambda: False, **kwargs):
        self.cancelled = cancelled

    def get(self, url):
        time.sleep(0.05)  # long enough that the progress dialog really appears
        if 'list=tag&id=' in url:
            return TAG_PAGES[url.rsplit('=', 1)[1]]
        if 'list=tag' in url:
            return TAG_INDEX
        raise IOError('unexpected url ' + url)


@unittest.skipUnless(HAVE_QT, 'PyQt6 (with its system libraries) is not installed')
class QtCase(unittest.TestCase):
    """Shared setup: real Qt, stubbed Calibre, and the freshly built plugin zips extracted as packages."""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.tmp = tempfile.TemporaryDirectory()
        cls.built = build_plugins.build_all(Path(cls.tmp.name) / 'dist')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.saved = {k: v for k, v in sys.modules.items() if k.startswith(('calibre', 'qt', 'calibre_plugins'))}
        qtcore = types.ModuleType('qt.core')
        for module in (QtWidgets, QtCore):
            for name in dir(module):
                setattr(qtcore, name, getattr(module, name))
        sys.modules['qt'] = types.ModuleType('qt')
        sys.modules['qt.core'] = qtcore
        for name in ('calibre', 'calibre.customize', 'calibre.gui2', 'calibre.gui2.actions', 'calibre.utils'):
            sys.modules[name] = MagicMock()
        config = types.ModuleType('calibre.utils.config')
        config.JSONConfig = lambda name: StubPrefs()
        sys.modules['calibre.utils.config'] = config
        sys.modules['calibre_plugins'] = types.ModuleType('calibre_plugins')
        sys.modules['calibre_plugins'].__path__ = []

    def tearDown(self):
        if hasattr(builtins, 'get_resources'):
            del builtins.get_resources
        for key in [k for k in sys.modules if k.startswith(('calibre', 'qt'))]:
            del sys.modules[key]
        sys.modules.update(self.saved)

    def load(self, import_name):
        target = Path(self.tmp.name) / import_name
        if not target.exists():
            zipfile.ZipFile(self.built[import_name]).extractall(target)
        package = types.ModuleType(f'calibre_plugins.{import_name}')
        package.__path__ = [str(target)]
        sys.modules[package.__name__] = package
        return package.__name__



@unittest.skipUnless(HAVE_QT, 'PyQt6 (with its system libraries) is not installed')
class TaskAndTagSearchTests(QtCase):
    def test_finished_task_is_not_reported_as_cancelled(self):
        guikit = importlib.import_module(self.load('metabods_downloader') + '.guikit')
        task = guikit.run_task(None, 'Working…', lambda t: (time.sleep(0.3), ['done'])[1])
        self.assertEqual(task.result, ['done'])
        self.assertFalse(task.cancelled(), 'a run nobody cancelled must not look cancelled afterwards')

    def test_pressing_cancel_is_still_reported(self):
        guikit = importlib.import_module(self.load('metabods_downloader') + '.guikit')

        def press_cancel():
            for widget in QtWidgets.QApplication.topLevelWidgets():
                if isinstance(widget, QtWidgets.QProgressDialog) and widget.isVisible():
                    widget.findChild(QtWidgets.QPushButton).click()  # what a user does; QProgressDialog.cancel() alone emits nothing

        def work(task):
            for _ in range(200):
                if task.cancelled():
                    return 'stopped early'
                time.sleep(0.05)
            return 'ran to the end'

        QtCore.QTimer.singleShot(300, press_cancel)
        task = guikit.run_task(None, 'Working…', work)
        self.assertTrue(task.cancelled())
        self.assertEqual(task.result, 'stopped early')

    def test_metabods_tag_search_fills_the_story_list(self):
        package = self.load('metabods_downloader')
        core = importlib.import_module(package + '.core')
        core.Fetcher = FakeFetcher  # the dialog reaches the site only through core.Fetcher
        ui = importlib.import_module(package + '.ui')
        dialog = ui.TagSearchDialog(None, existing_ids={'three'})
        self.assertEqual(dialog.tag_list.count(), 2, 'the tag list should load (All Tags is skipped)')

        def check(*names):
            dialog.checked_tags.clear()
            for i in range(dialog.tag_list.count()):
                item = dialog.tag_list.item(i)
                if item.text().lstrip('★ ') in names:
                    item.setCheckState(QtCore.Qt.CheckState.Checked)
            self.assertEqual(len(dialog.checked_tags), len(names))

        check('Alpha', 'Beta')
        dialog.mode.setCurrentIndex(0)  # any checked tag
        dialog.search()
        titles = [dialog.result_list.item(i).text() for i in range(dialog.result_list.count())]
        self.assertEqual(len(titles), 3, titles)
        self.assertTrue(any('Story Three' in t and 'already in library' in t for t in titles))
        self.assertEqual(dialog.selected_ids(), ['one', 'two'], 'stories already in the library start unchecked')
        self.assertIn('3 stories found', dialog.summary.text())

        dialog.mode.setCurrentIndex(1)  # all checked tags: only the story in both lists
        dialog.search()
        self.assertEqual([dialog.result_list.item(i).data(QtCore.Qt.ItemDataRole.UserRole) for i in range(dialog.result_list.count())], ['two'])


NIFTY_SECTION = '<a href="/nifty/gay/college/">College</a><a href="/nifty/gay/camping/">Camping</a>'
NIFTY_CATEGORY = ('<div class="ftr" role="row"><div>Dir</div><div>Oct 7 07:25</div><div><a href="campus-rivals/">campus-rivals/</a></div></div>'
                  '<div class="ftr" role="row"><div>7K</div><div>Oct 4 16:39</div><div><a href="my-story">my-story</a></div></div>')


class NiftyFakeFetcher(FakeFetcher):
    def get(self, url):
        if url.endswith('/nifty/gay/'):
            return NIFTY_SECTION
        if url.endswith('/gay/college/') or url.endswith('/gay/camping/'):
            return NIFTY_CATEGORY
        raise IOError('unexpected url ' + url)


@unittest.skipUnless(HAVE_QT, 'PyQt6 (with its system libraries) is not installed')
class OtherDialogTests(QtCase):
    """Same real-Qt setup, for the remaining dialogs."""

    def test_metabods_link_dialog(self):
        ui = importlib.import_module(self.load('metabods_downloader') + '.ui')
        dialog = ui.DownloadDialog(None)
        dialog.text.setPlainText('bennet-3120\n\n  https://metabods.com/mbxy/site/archive.php?list=author&id=368  \n')
        self.assertEqual(len(dialog.lines()), 2)
        skip, combine, title = dialog.options.values()
        self.assertEqual((skip, combine, title), (True, False, ''))
        dialog.options.combine.setChecked(True)
        dialog.options.title.setText('  Omnibus ')
        self.assertEqual(dialog.options.values(), (True, True, 'Omnibus'))

    def test_nifty_browse_dialog_loads_and_selects(self):
        package = self.load('nifty_downloader')
        core = importlib.import_module(package + '.core')
        core.Fetcher = NiftyFakeFetcher
        ui = importlib.import_module(package + '.ui')
        dialog = ui.BrowseDialog(None, existing_ids={'gay/college/my-story'})
        self.assertEqual([dialog.category.itemData(i) for i in range(dialog.category.count())], ['gay/college', 'gay/camping'])
        dialog.load_stories()
        self.assertEqual(dialog.story_list.count(), 2)
        texts = [dialog.story_list.item(i).text() for i in range(dialog.story_list.count())]
        self.assertTrue(any('my-story'.replace('-', ' ').title() in t and 'already in library' in t for t in texts), texts)
        dialog.set_shown(True)
        self.assertEqual(sorted(r['id'] for r in dialog.selected_refs()), ['gay/college/campus-rivals', 'gay/college/my-story'])
        dialog.filter.setText('rivals')
        self.assertEqual(dialog.story_list.count(), 1)
        self.assertEqual(len(dialog.selected_refs()), 2, 'filtering must not lose checked stories')
        dialog.toggle_favorite()
        self.assertIn('gay/college', dialog.favorites)
        self.assertEqual(dialog.favs.count(), 2)

    def test_nifty_link_dialog(self):
        ui = importlib.import_module(self.load('nifty_downloader') + '.ui')
        dialog = ui.LinksDialog(None)
        dialog.text.setPlainText('https://www.nifty.org/nifty/gay/college/\n\n')
        self.assertEqual(dialog.lines(), ['https://www.nifty.org/nifty/gay/college/'])


@unittest.skipUnless(HAVE_QT, 'PyQt6 (with its system libraries) is not installed')
class FanficDialogTests(QtCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'fanfic_downloader' not in cls.built:
            raise unittest.SkipTest('fanfic zip needs FanFicFare installed to build')

    def setUp(self):
        super().setUp()
        package = self.load('fanfic_downloader')
        self.path = str(Path(self.tmp.name) / 'fanfic_downloader')
        sys.path.insert(0, self.path)  # what `with plugin:` does for the bundled third-party libraries
        zf = zipfile.ZipFile(self.built['fanfic_downloader'])
        builtins.get_resources = lambda name: zf.read(name)  # Calibre injects this into plugin modules
        self.package = package

    def tearDown(self):
        sys.path.remove(self.path)
        for key in [k for k in sys.modules if k.startswith(('fanficfare', 'cloudscraper', 'requests_file', 'requests_toolbelt', 'brotlidecpy'))]:
            del sys.modules[key]
        super().tearDown()

    def test_download_dialog_and_sites_listing(self):
        ui = importlib.import_module(self.package + '.ui')
        dialog = ui.DownloadDialog(None)
        dialog.urls.setPlainText('https://www.royalroad.com/fiction/21220\n\n')
        values = dialog.values()
        self.assertEqual((values['lines'], values['allow_adult'], values['skip']), (['https://www.royalroad.com/fiction/21220'], False, True))
        dialog.adult.setChecked(True)
        dialog.extra.setPlainText('Custom.net # note')
        values = dialog.values()
        self.assertEqual((values['allow_adult'], values['extra_adult']), (True, ['custom.net']))
        sites = ui.SitesDialog(dialog)
        self.assertIn('www.royalroad.com', sites.findChild(QtWidgets.QPlainTextEdit).toPlainText())

    def test_royal_road_setup_dialog(self):
        ui = importlib.import_module(self.package + '.ui')
        flaresolverr = importlib.import_module(self.package + '.flaresolverr')
        advanced = QtWidgets.QPlainTextEdit('[archiveofourown.org]\nis_adult:true\n')
        dialog = ui.RoyalRoadSetupDialog(None, advanced)
        self.assertIn('FlareSolverr', dialog.findChild(QtWidgets.QTextBrowser).toPlainText(), 'the bundled guide should be shown')
        self.assertIn('not switched on', dialog.status.text())
        self.assertFalse(dialog.start_button.isEnabled(), 'no program chosen yet')
        self.assertFalse(dialog.stop_button.isEnabled())
        dialog.enable()
        self.assertIn('[www.royalroad.com]\nuse_flaresolverr_proxy:true', advanced.toPlainText())
        self.assertIn('is_adult:true', advanced.toPlainText())
        self.assertIn('switched on', dialog.status.text())
        dialog.copy_docker()
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), flaresolverr.DOCKER_COMMAND)
        advanced.setPlainText(advanced.toPlainText() + '\n[defaults]\nflaresolverr_proxy_port:1\n')  # nothing listens on port 1
        dialog.test_server()
        self.assertTrue(dialog.status.text().startswith('Problem: Nothing answered'), dialog.status.text())
        self.assertIn('localhost:1/v1', dialog.status.text(), 'the port from Advanced settings should be used')


if __name__ == '__main__':
    unittest.main()
