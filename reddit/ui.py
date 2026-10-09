"""Dialogs for following Reddit stories. Network work happens in the action, never here."""
import time
import webbrowser

from qt.core import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                     QLineEdit, QMessageBox, QPushButton, QRadioButton, QTableWidget, QTableWidgetItem, Qt, QVBoxLayout)

from calibre_plugins.reddit_follower import core, login
from calibre_plugins.reddit_follower.config import prefs
from calibre_plugins.reddit_follower.guikit import run_task
from calibre_plugins.reddit_follower.storykit import Fetcher

ACCESS_NOTE = (
    'Two ways to read Reddit, and what is known about each:\n'
    '• Public feeds (no account): the same Atom feeds a feed reader uses. They need nothing from you, but only reach the newest '
    'posts, and Reddit\'s robots.txt asks automated clients to stay out, so this is a light, personal-reader use. Reddit may refuse '
    '(HTTP 429/403); when it does the plugin stops and tries later instead of pushing.\n'
    '• Official API (your own credentials): the route Reddit documents. Reddit now requires approval before new apps get API '
    'access (per its Responsible Builder Policy; I could not confirm the current process from Reddit itself). Register an app of '
    'type "installed app" at reddit.com/prefs/apps once approved, enter its client id here and use Log in with Reddit. This path is written to '
    'Reddit\'s documentation but has not been tried against the live service.'
)


class FollowDialog(QDialog):
    """Add or edit one followed series."""

    def __init__(self, parent, follow=None):
        super().__init__(parent)
        self.setWindowTitle('Follow a Reddit story' if follow is None else 'Edit followed story')
        self.resize(560, 360)
        self.follow = follow
        layout = QVBoxLayout(self)
        if follow is None:
            row = QHBoxLayout()
            row.addWidget(QLabel('Quick start'))
            self.preset = QComboBox()
            self.preset.addItem('Fill in by hand…')
            for preset in core.PRESETS:
                self.preset.addItem(preset['label'])
            self.preset.currentIndexChanged.connect(self.use_preset)
            row.addWidget(self.preset, 1)
            layout.addLayout(row)
        form = QFormLayout()
        self.name = QLineEdit(follow['name'] if follow else '')
        self.name.setPlaceholderText('Book title, for example Out of Cruel Space')
        form.addRow('Book title', self.name)
        self.source = QLineEdit(core.source_text(follow['source']) if follow else '')
        self.source.setPlaceholderText('r/HFY   or   u/author   or a Reddit search address')
        self.source.textChanged.connect(self.check_source)
        form.addRow('Where to look', self.source)
        self.title_filter = QLineEdit(follow['title_filter'] if follow else '')
        self.title_filter.setPlaceholderText('Only posts whose title contains this (or re:regular expression)')
        form.addRow('Title contains', self.title_filter)
        self.author_filter = QLineEdit(follow['author_filter'] if follow else '')
        self.author_filter.setPlaceholderText('Only posts by this user (optional)')
        form.addRow('Posted by', self.author_filter)
        layout.addLayout(form)
        self.author_note = QCheckBox("Also keep the author's own comment under each chapter (official API only)")
        self.author_note.setToolTip('Authors often use their comment for notes, prefaces or links. Costs one extra request per chapter, '
                                    'so a long series takes a while on the first pass; reader comments are not included.')
        self.author_note.setChecked(bool(follow and follow.get('author_note')))
        layout.addWidget(self.author_note)
        self.message = QLabel('')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        layout.addWidget(QLabel(
            'Tip: for one series inside a busy subreddit, use a search address, for example the one Reddit shows when you search the '
            'series name inside r/HFY, or follow the author with u/name, and set "Title contains" so only that series is kept. '
            'Each matching post becomes a chapter, oldest first, in one book that grows as new posts appear.'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.try_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.check_source()

    def use_preset(self, index):
        if index <= 0:
            return
        preset = core.PRESETS[index - 1]
        self.name.setText(preset['name'])
        self.source.setText(preset['source'])
        self.title_filter.setText(preset['title_filter'])
        self.author_filter.setText(preset['author_filter'])

    def check_source(self, *_):
        text = self.source.text().strip()
        if not text:
            self.message.setText('')
            return None
        try:
            src = core.parse_source(text)
        except core.SourceError as exc:
            self.message.setText(str(exc))
            return None
        self.message.setText(f'Will follow {core.describe_source(src)}.')
        return src

    def try_accept(self):
        if self.check_source() is None:
            if not self.source.text().strip():
                self.message.setText('Enter where to look first.')
            return
        self.accept()

    def result_follow(self):
        """A new follow, or the edited existing one (keeping its id and history)."""
        if self.follow is None:
            return core.new_follow(self.name.text(), self.source.text(), self.title_filter.text(), self.author_filter.text(), self.author_note.isChecked())
        updated = core.new_follow(self.name.text() or self.follow['name'], self.source.text(), self.title_filter.text(), self.author_filter.text(), self.author_note.isChecked())
        updated.update(id=self.follow['id'], last_checked=0.0, last_status='changed; will be checked again')
        return updated


class SettingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('Reddit Story Follower settings')
        self.resize(640, 560)
        layout = QVBoxLayout(self)
        note = QLabel(ACCESS_NOTE)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.rss = QRadioButton('Read public feeds (no account)')
        self.api = QRadioButton('Use the official API with my own credentials')
        (self.api if prefs['mode'] == 'api' else self.rss).setChecked(True)
        layout.addWidget(self.rss)
        layout.addWidget(self.api)
        form = QFormLayout()
        self.client_id = QLineEdit(prefs['client_id'])
        self.client_secret = QLineEdit(prefs['client_secret'])
        self.client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.client_secret.setPlaceholderText('Leave empty for an "installed app"')
        self.username = QLineEdit(prefs['username'])
        self.username.setPlaceholderText('Your Reddit username, shown to Reddit in the user agent')
        form.addRow('Client id', self.client_id)
        form.addRow('Client secret', self.client_secret)
        form.addRow('Reddit username', self.username)
        layout.addLayout(form)
        self.refresh_token, self.account_name = prefs['refresh_token'], prefs['account_name']
        row = QHBoxLayout()
        self.login_button = QPushButton('Log in with Reddit…')
        self.login_button.setToolTip('Opens Reddit in your browser to approve read access. Your password never reaches this plugin.')
        self.login_button.clicked.connect(self.log_in)
        self.logout_button = QPushButton('Log out')
        self.logout_button.clicked.connect(self.log_out)
        self.login_status = QLabel('')
        row.addWidget(self.login_button)
        row.addWidget(self.logout_button)
        row.addWidget(self.login_status, 1)
        layout.addLayout(row)
        hint = QLabel('Register the app at reddit.com/prefs/apps with redirect uri exactly:  ' + login.REDIRECT_URI)
        hint.setWordWrap(True)
        hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(hint)
        self.api.toggled.connect(self.sync)
        self.sync()
        self.auto = QCheckBox('Check for new chapters automatically while Calibre is open')
        self.auto.setChecked(bool(prefs['auto_check']))
        layout.addWidget(self.auto)
        row = QHBoxLayout()
        row.addWidget(QLabel('Check each story at most every'))
        self.hours = QDoubleSpinBox()
        self.hours.setRange(core.MIN_CHECK_HOURS, 168)
        self.hours.setDecimals(1)
        self.hours.setSuffix(' hours')
        self.hours.setValue(max(float(prefs['check_hours']), core.MIN_CHECK_HOURS))
        row.addWidget(self.hours)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(QLabel('Checks only run while Calibre is open (there is no background service), and the interval is never shorter than one hour.'))
        row = QHBoxLayout()
        test = QPushButton('Test connection')
        test.setToolTip('Makes one request to r/HFY with the settings above (nothing is saved or changed)')
        test.clicked.connect(self.test_connection)
        row.addWidget(test)
        self.test_result = QLabel('')
        self.test_result.setWordWrap(True)
        row.addWidget(self.test_result, 1)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def sync(self, *_):
        for widget in (self.client_id, self.client_secret, self.username):
            widget.setEnabled(self.api.isChecked())
        self.login_button.setEnabled(self.api.isChecked())
        self.logout_button.setEnabled(bool(self.refresh_token))
        self.login_status.setText(f'Logged in as u/{self.account_name}' if self.refresh_token and self.account_name
                                  else 'Logged in' if self.refresh_token else 'Not logged in')

    open_browser = staticmethod(webbrowser.open)
    login_endpoints = {}  # tests point these at a stand-in server

    def log_in(self):
        client_id, secret = self.client_id.text().strip(), self.client_secret.text().strip()
        if not client_id:
            QMessageBox.warning(self, 'Reddit Story Follower', 'Enter your app\'s client id first.')
            return
        try:
            with login.CallbackServer() as server:
                task = run_task(self, 'Waiting for you to approve the login in your browser…', lambda t: login.log_in(
                    Fetcher(cancelled=t.cancelled), client_id, secret, server, self.open_browser, t.cancelled,
                    **{k: v for k, v in self.login_endpoints.items() if k != 'revoke_url'}))
        except login.LoginError as exc:
            QMessageBox.warning(self, 'Reddit Story Follower', str(exc))
            return
        if task.error:
            if 'cancelled' not in str(task.error).lower():
                QMessageBox.warning(self, 'Reddit Story Follower', f'Login failed: {task.error}')
            return
        if task.result:
            self.refresh_token = task.result['refresh_token']
            self.account_name = task.result['username']
            prefs['refresh_token'], prefs['account_name'] = self.refresh_token, self.account_name
            self.sync()

    def log_out(self):
        if self.refresh_token:
            revoked = login.revoke(Fetcher(), self.client_id.text().strip(), self.client_secret.text().strip(), self.refresh_token,
                                   self.login_endpoints.get('revoke_url'))
            if not revoked:
                QMessageBox.information(self, 'Reddit Story Follower', 'Reddit could not be reached to cancel the login, so it was only '
                                        'removed here. You can also remove it at reddit.com/prefs/apps.')
        self.refresh_token = self.account_name = ''
        prefs['refresh_token'] = prefs['account_name'] = ''
        self.sync()

    def test_connection(self):
        mode = 'api' if self.api.isChecked() else 'rss'
        client_id, secret, username = self.client_id.text().strip(), self.client_secret.text().strip(), self.username.text().strip()
        src = core.parse_source('r/HFY')
        task = run_task(self, 'Testing Reddit…', lambda t: core.probe(core.make_source(mode, client_id, secret, self.account_name or username, t.cancelled, self.refresh_token), src, limit=5))
        if task.error:
            self.test_result.setText(f'The test failed: {task.error}')
        elif task.result is not None:
            self.test_result.setText(('OK: ' if task.result[0] else 'Problem: ') + task.result[1])

    def save(self):
        if self.api.isChecked() and not self.client_id.text().strip():
            QMessageBox.warning(self, 'Reddit Story Follower', 'Enter your app\'s client id to use the official API, or choose public feeds.')
            return
        prefs['mode'] = 'api' if self.api.isChecked() else 'rss'
        prefs['client_id'] = self.client_id.text().strip()
        prefs['client_secret'] = self.client_secret.text().strip()
        prefs['username'] = self.username.text().strip()
        prefs['auto_check'] = self.auto.isChecked()
        prefs['check_hours'] = max(self.hours.value(), core.MIN_CHECK_HOURS)
        self.accept()


class ManageDialog(QDialog):
    """The list of followed stories, with add, edit, remove and check buttons."""
    COLUMNS = ['Book', 'Following', 'Chapters', 'Last checked', 'Status']

    def __init__(self, parent, action):
        super().__init__(parent)
        self.action = action
        self.setWindowTitle('Followed Reddit stories')
        self.resize(860, 460)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        self.mode_label = QLabel('')
        layout.addWidget(self.mode_label)
        row = QHBoxLayout()
        for label, slot in (('Add…', self.add), ('Edit…', self.edit), ('Remove', self.remove), ('Test selected', self.test_selected), ('Check selected now', self.check_selected),
                            ('Check all now', self.check_all), ('Settings…', self.settings)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            row.addWidget(button)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def follows(self):
        return prefs['follows']

    def refresh(self):
        follows = self.follows()
        self.table.setRowCount(len(follows))
        for r, follow in enumerate(follows):
            checked = time.strftime('%Y-%m-%d %H:%M', time.localtime(follow['last_checked'])) if follow.get('last_checked') else 'never'
            filt = ''.join([f"  title has “{follow['title_filter']}”" if follow['title_filter'] else '',
                            f"  by {follow['author_filter']}" if follow['author_filter'] else ''])
            cells = [follow['name'], core.describe_source(follow['source']) + filt, str(self.action.chapter_count(follow)), checked, follow.get('last_status', '')]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, follow['id'])
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.mode_label.setText('Reading: ' + ('the official API' if prefs['mode'] == 'api' else 'public feeds')
                                + ('; automatic checks every %.1f hours.' % max(float(prefs['check_hours']), core.MIN_CHECK_HOURS) if prefs['auto_check'] else '; automatic checks are off.'))

    def selected_ids(self):
        rows = {i.row() for i in self.table.selectedItems()}
        return [self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in sorted(rows)]

    def add(self):
        dialog = FollowDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            prefs['follows'] = prefs['follows'] + [dialog.result_follow()]
            self.refresh()

    def edit(self):
        ids = self.selected_ids()
        if len(ids) != 1:
            return
        current = next(f for f in self.follows() if f['id'] == ids[0])
        dialog = FollowDialog(self, current)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated = dialog.result_follow()
            prefs['follows'] = [updated if f['id'] == current['id'] else f for f in self.follows()]
            self.refresh()

    def remove(self):
        ids = self.selected_ids()
        if not ids:
            return
        if QMessageBox.question(self, 'Remove', f'Stop following {len(ids)} story/stories? The books already in your library are kept.',
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        for follow in [f for f in self.follows() if f['id'] in ids]:
            core.ChapterCache(self.action.cache_dir(), follow['id']).delete()
        prefs['follows'] = [f for f in self.follows() if f['id'] not in ids]
        self.refresh()

    def test_selected(self):
        ids = self.selected_ids()
        if len(ids) == 1:
            self.action.test_follow(next(f for f in self.follows() if f['id'] == ids[0]))

    def check_selected(self):
        ids = self.selected_ids()
        self.action.check_now([f for f in self.follows() if f['id'] in ids])
        self.refresh()

    def check_all(self):
        self.action.check_now(list(self.follows()))
        self.refresh()

    def settings(self):
        SettingsDialog(self).exec()
        self.refresh()
