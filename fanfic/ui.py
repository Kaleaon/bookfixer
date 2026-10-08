"""Fanfic downloader dialog. Network work never runs on the GUI thread (see guikit.run_task)."""
from qt.core import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                     QTextBrowser, QVBoxLayout)

from calibre_plugins.fanfic_downloader import engine, flaresolverr
from calibre_plugins.fanfic_downloader.config import prefs
from calibre_plugins.fanfic_downloader.guikit import run_task

ADVANCED_HELP = '''# FanFicFare personal.ini settings, optional. Examples (remove the # to use).
# Each [section] header may appear only once: put all of a site's lines under one header.
#
# Royal Road through a FlareSolverr server you run yourself (see docs/royalroad-flaresolverr.md):
#[www.royalroad.com]
#use_flaresolverr_proxy:true
#
# A login for one site:
#[www.royalroad.com]
#username:you@example.com
#password:your-password
#
# Read pages from your browser's cache instead:
#[defaults]
#browser_cache_path:/home/you/.cache/google-chrome/Default/Cache/Cache_Data
#[www.royalroad.com]
#use_browser_cache:true
'''


def guide_text():
    """The Royal Road / FlareSolverr guide, shipped inside the plugin zip."""
    try:
        data = get_resources('royalroad-flaresolverr.md')  # noqa: F821  injected by Calibre's plugin loader
    except NameError:
        data = None
    return data.decode('utf-8') if data else 'The setup guide is missing from this copy of the plugin.'


class RoyalRoadSetupDialog(QDialog):
    """Guide plus helpers: copy the Docker command, test the FlareSolverr server, and switch it on for Royal Road."""

    def __init__(self, parent, advanced_edit):
        super().__init__(parent)
        self.advanced = advanced_edit  # the dialog's Advanced settings box; changes here are saved when that dialog is accepted
        self.setWindowTitle('Royal Road setup (FlareSolverr)')
        self.resize(760, 680)
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setMarkdown(guide_text())
        layout.addWidget(browser, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        for label, slot in (('Copy Docker command', self.copy_docker), ('Test: is FlareSolverr running?', self.test_server),
                            ('Test: load Royal Road through it', self.test_site), ('Enable for Royal Road', self.enable)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            row.addWidget(button)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.show_enabled_state()

    def settings(self):
        return flaresolverr.settings_from_ini(self.advanced.toPlainText())

    def show_enabled_state(self):
        on = flaresolverr.is_enabled(self.advanced.toPlainText())
        self.status.setText('FlareSolverr is switched on for Royal Road in Advanced settings.' if on else
                            'FlareSolverr is not switched on for Royal Road yet (the last button does that).')

    def copy_docker(self):
        QApplication.clipboard().setText(flaresolverr.DOCKER_COMMAND)
        self.status.setText('Docker command copied. Paste it into a terminal (Command Prompt or PowerShell on Windows).')

    def _run(self, title, func):
        task = run_task(self, title, lambda t: func())
        if task.error:
            self.status.setText(f'Test failed unexpectedly: {task.error}')
        elif task.result is not None:
            self.status.setText(('OK: ' if task.result[0] else 'Problem: ') + task.result[1])

    def test_server(self):
        settings = self.settings()
        self._run('Checking FlareSolverr…', lambda: flaresolverr.check_server(settings))

    def test_site(self):
        settings = self.settings()
        self._run('Loading Royal Road through FlareSolverr (up to a minute)…', lambda: flaresolverr.fetch_through(settings))

    def enable(self):
        text, changed = flaresolverr.enable_in_ini(self.advanced.toPlainText())
        if changed:
            self.advanced.setPlainText(text)
        self.show_enabled_state()
        self.status.setText(self.status.text() + (' Saved when you press OK in the download window.' if changed else ''))


class SitesDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('Supported sites')
        self.resize(640, 520)
        layout = QVBoxLayout(self)
        extra = engine.parse_extra_adult(prefs['extra_adult'])
        rows = engine.supported_sites(extra_adult=extra)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText('\n'.join(f"{'[adult] ' if adult else '        '}{domain}    e.g. {example}" for domain, example, adult in rows))
        layout.addWidget(text)
        layout.addWidget(QLabel('[adult] sites are only used when "Allow adult sites" is on.'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class DownloadDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('Download fanfiction and web serials')
        self.resize(640, 640)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('One story address per line. Add a chapter range like [1-5], [3-] or [-4] to the end of an address '
                                'to fetch only those chapters.'))
        self.urls = QPlainTextEdit()
        self.urls.setPlaceholderText('https://www.royalroad.com/fiction/21220\nhttps://archiveofourown.org/works/51711850')
        layout.addWidget(self.urls, 2)

        self.adult = QCheckBox('Allow adult sites (adult-only sites, and confirming adult content on mixed sites)')
        self.adult.setChecked(bool(prefs['allow_adult']))
        layout.addWidget(self.adult)
        layout.addWidget(QLabel('Extra domains to treat as adult sites (one per line):'))
        self.extra = QPlainTextEdit(prefs['extra_adult'])
        self.extra.setMaximumHeight(60)
        layout.addWidget(self.extra)
        self.skip = QCheckBox('Skip stories already in this library (matched by their address)')
        self.skip.setChecked(bool(prefs['skip_existing']))
        layout.addWidget(self.skip)

        layout.addWidget(QLabel('Advanced settings (FanFicFare personal.ini format) for logins, browser cache, proxies:'))
        self.advanced = QPlainTextEdit(prefs['advanced_ini'])
        self.advanced.setPlaceholderText(ADVANCED_HELP)
        layout.addWidget(self.advanced, 2)

        row = QHBoxLayout()
        sites = QPushButton('Supported sites…')
        sites.clicked.connect(lambda: SitesDialog(self).exec())
        row.addWidget(sites)
        royal = QPushButton('Royal Road setup…')
        royal.clicked.connect(lambda: RoyalRoadSetupDialog(self, self.advanced).exec())
        row.addWidget(royal)
        row.addStretch(1)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        prefs['allow_adult'] = self.adult.isChecked()
        prefs['extra_adult'] = self.extra.toPlainText()
        prefs['skip_existing'] = self.skip.isChecked()
        prefs['advanced_ini'] = self.advanced.toPlainText()
        return {
            'lines': [line for line in self.urls.toPlainText().splitlines() if line.strip()],
            'allow_adult': self.adult.isChecked(),
            'extra_adult': engine.parse_extra_adult(self.extra.toPlainText()),
            'skip': self.skip.isChecked(),
            'ini': self.advanced.toPlainText(),
        }
