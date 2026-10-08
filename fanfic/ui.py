"""Fanfic downloader dialog. Network work never runs on the GUI thread (see guikit.run_task)."""
from qt.core import (QCheckBox, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QHBoxLayout)

from calibre_plugins.fanfic_downloader import engine
from calibre_plugins.fanfic_downloader.config import prefs

ADVANCED_HELP = '''# FanFicFare personal.ini settings, optional. Examples (remove the # to use):
#[www.royalroad.com]
#username:you@example.com
#password:your-password
#
#[defaults]
#use_browser_cache:true
#browser_cache_path:/home/you/.cache/google-chrome/Default/Cache/Cache_Data
#
#[defaults]
#use_flaresolverr_proxy:true
'''


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
