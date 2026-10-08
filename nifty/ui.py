"""Nifty dialogs. Network work never runs on the GUI thread (see guikit.run_task)."""
from qt.core import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                     QListWidgetItem, QPlainTextEdit, QPushButton, Qt, QVBoxLayout)

from calibre_plugins.nifty_downloader import core
from calibre_plugins.nifty_downloader.config import prefs
from calibre_plugins.nifty_downloader.guikit import DownloadOptions, run_task


class LinksDialog(QDialog):
    """Paste Nifty story files, series folders or category folders."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('Download Nifty stories')
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('One address per line: a story file, a series folder, or a category folder (for example '
                                'https://www.nifty.org/nifty/gay/college/). A chapter link downloads the whole series.'))
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText('https://www.nifty.org/nifty/gay/college/the-brotherhood/')
        layout.addWidget(self.text)
        self.options = DownloadOptions(self, prefs)
        layout.addWidget(self.options)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def lines(self):
        return [line for line in self.text.toPlainText().splitlines() if line.strip()]


class BrowseDialog(QDialog):
    """Pick a section and category, filter its stories, tick the ones to download."""

    def __init__(self, parent, existing_ids):
        super().__init__(parent)
        self.setWindowTitle('Browse Nifty by category')
        self.resize(760, 640)
        self.existing = existing_ids
        self.favorites = list(prefs['favorite_categories'])
        self.refs = []
        self.checked = set()
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        self.section = QComboBox()
        self.section.addItems(core.SECTIONS)
        self.section.currentIndexChanged.connect(self.load_categories)
        row.addWidget(QLabel('Section'))
        row.addWidget(self.section)
        self.category = QComboBox()
        self.category.setMinimumWidth(240)
        row.addWidget(QLabel('Category'))
        row.addWidget(self.category, 1)
        star = QPushButton('★ Toggle favorite')
        star.clicked.connect(self.toggle_favorite)
        row.addWidget(star)
        load = QPushButton('Load stories')
        load.clicked.connect(self.load_stories)
        row.addWidget(load)
        layout.addLayout(row)

        self.favs = QComboBox()
        self.favs.activated.connect(self.jump_to_favorite)
        layout.addWidget(self.favs)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText('Filter stories by title…')
        self.filter.textChanged.connect(self.fill_stories)
        layout.addWidget(self.filter)
        self.summary = QLabel('')
        layout.addWidget(self.summary)
        self.story_list = QListWidget()
        self.story_list.itemChanged.connect(self.story_toggled)
        layout.addWidget(self.story_list, 1)
        row = QHBoxLayout()
        for label, state in (('Check shown', True), ('Uncheck shown', False)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, s=state: self.set_shown(s))
            row.addWidget(b)
        row.addStretch(1)
        layout.addLayout(row)
        self.options = DownloadOptions(self, prefs)
        layout.addWidget(self.options)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Download checked')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh_favorites()
        self.load_categories()

    # -- categories
    def current_path(self):
        cat = self.category.currentData()
        return cat

    def load_categories(self, *_):
        section = self.section.currentText()
        task = run_task(self, 'Loading categories…', lambda t: core.parse_categories(
            core.Fetcher(cancelled=t.cancelled).get(core.url_for(section + '/')), section))
        self.category.clear()
        if task.error:
            self.summary.setText(f'Could not load categories: {task.error}')
            return
        for cat in task.result or []:
            path = f'{section}/{cat}'
            self.category.addItem(('★ ' if path in self.favorites else '') + core.humanize(cat), path)

    def refresh_favorites(self):
        self.favs.clear()
        self.favs.addItem('Favorite categories…', None)
        for path in self.favorites:
            self.favs.addItem('★ ' + ' / '.join(core.humanize(p) for p in path.split('/')), path)

    def toggle_favorite(self):
        path = self.current_path()
        if not path:
            return
        self.favorites = [f for f in self.favorites if f != path] if path in self.favorites else self.favorites + [path]
        prefs['favorite_categories'] = self.favorites
        self.refresh_favorites()
        self.load_categories()
        index = self.category.findData(path)
        if index >= 0:
            self.category.setCurrentIndex(index)

    def jump_to_favorite(self, index):
        path = self.favs.itemData(index)
        if not path:
            return
        section = path.split('/')[0]
        if section != self.section.currentText():
            self.section.setCurrentText(section)  # reloads that section's categories
        i = self.category.findData(path)
        if i >= 0:
            self.category.setCurrentIndex(i)
            self.load_stories()

    # -- stories
    def load_stories(self):
        path = self.current_path()
        if not path:
            return
        task = run_task(self, 'Loading stories…', lambda t: core.expand_dir(core.Fetcher(cancelled=t.cancelled), path))
        if task.error:
            self.summary.setText(f'Could not load stories: {task.error}')
            return
        if task.result is None:
            return
        self.refs = task.result
        self.checked = set()
        self.fill_stories()

    def in_library(self, ref):
        return any(e == ref['id'] or e.startswith(ref['id'] + '/') for e in self.existing)

    def fill_stories(self, *_):
        needle = self.filter.text().strip().casefold()
        self.story_list.blockSignals(True)
        self.story_list.clear()
        for ref in self.refs:
            if needle not in ref['title'].casefold():
                continue
            have = self.in_library(ref)
            item = QListWidgetItem(f"{ref['title']} — {ref['detail']}, {ref['date']}" + ('   (already in library)' if have else ''))
            item.setData(Qt.ItemDataRole.UserRole, ref['id'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if ref['id'] in self.checked else Qt.CheckState.Unchecked)
            self.story_list.addItem(item)
        self.story_list.blockSignals(False)
        in_lib = sum(self.in_library(r) for r in self.refs)
        self.summary.setText(f'{len(self.refs)} entries ({in_lib} already in your library). {len(self.checked)} checked.')

    def story_toggled(self, item):
        rid = item.data(Qt.ItemDataRole.UserRole)
        (self.checked.add if item.checkState() == Qt.CheckState.Checked else self.checked.discard)(rid)
        self.summary.setText(f'{len(self.refs)} entries. {len(self.checked)} checked.')

    def set_shown(self, state):
        for i in range(self.story_list.count()):
            self.story_list.item(i).setCheckState(Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)

    def selected_refs(self):
        return [r for r in self.refs if r['id'] in self.checked]
