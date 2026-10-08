from io import BytesIO
from calibre.gui2.actions import InterfaceAction
from calibre.gui2 import error_dialog, info_dialog
from calibre.utils.config import JSONConfig
from qt.core import (QAction, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QLabel, QMenu,
                     QPlainTextEdit, QVBoxLayout)
from calibre_plugins.epub_promo_scrubber.core import Matcher, scrub_epub, scrub_files, tidy

prefs = JSONConfig('plugins/epub_promo_scrubber')
prefs.defaults.update(extra_patterns='', heuristic=True, drop_empty_pages=True, backup=True, in_place=False)


class ScrubAction(InterfaceAction):
    name = 'EPUB Promo Scrubber'
    action_spec = ('EPUB Promo Scrubber', None, 'Remove site promotions from EPUB books', None)

    def genesis(self):
        menu = QMenu(self.gui)
        self.qaction.setMenu(menu)
        for title, slot in [('Scrub selected books in Calibre', self.scrub_selected),
                            ('Scrub EPUB file or folder to a new folder…', self.scrub_folder),
                            ('Settings…', self.settings)]:
            action = QAction(title, self.gui)
            action.triggered.connect(lambda checked=False, slot=slot: slot())
            menu.addAction(action)
        self.qaction.triggered.connect(self.scrub_selected)

    def options(self):
        extra = [line for line in prefs['extra_patterns'].splitlines() if line.strip()]
        return extra, prefs['heuristic'], prefs['drop_empty_pages']

    def settings(self):
        dialog = QDialog(self.gui)
        dialog.setWindowTitle('EPUB Promo Scrubber settings')
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Built in: OceanofPDF, PDFDrive, Z-Library, LibGen and similar names, URLs and links.\n'
                                'Extra site names or domains to remove, one per line (prefix a line with re: for a regular expression):'))
        patterns = QPlainTextEdit(prefs['extra_patterns'])
        layout.addWidget(patterns)
        heuristic = QCheckBox('Also remove short "Downloaded from <website>" / "free ebooks" style blocks from any site')
        heuristic.setChecked(prefs['heuristic'])
        drop = QCheckBox('Delete pages that contain nothing but promotion (and their contents entries)')
        drop.setChecked(prefs['drop_empty_pages'])
        backup = QCheckBox('Library books: keep the unmodified EPUB as ORIGINAL_EPUB (untick to replace the original with the cleaned version and discard any existing backup)')
        backup.setChecked(prefs['backup'])
        in_place = QCheckBox('Files and folders: replace the original files with cleaned versions instead of writing copies to another folder')
        in_place.setChecked(prefs['in_place'])
        for box in (heuristic, drop, backup, in_place):
            layout.addWidget(box)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            prefs['extra_patterns'] = patterns.toPlainText()
            prefs['heuristic'] = heuristic.isChecked()
            prefs['drop_empty_pages'] = drop.isChecked()
            prefs['backup'] = backup.isChecked()
            prefs['in_place'] = in_place.isChecked()

    def scrub_selected(self):
        ids = list(self.gui.library_view.get_selected_ids())
        if not ids:
            info_dialog(self.gui, 'EPUB Promo Scrubber', 'Select one or more books in Calibre first.', show=True)
            return
        extra, heuristic, drop = self.options()
        db = self.gui.current_db.new_api
        matcher = Matcher(extra, heuristic)
        changed, unchanged, errors = [], 0, []
        for book_id in ids:
            try:
                data = db.format(book_id, 'EPUB')
                if not data:
                    continue
                new, report = scrub_epub(data, extra, heuristic, drop)
                if new is not None:
                    if prefs['backup']:
                        db.save_original_format(book_id, 'EPUB')
                    elif 'ORIGINAL_EPUB' in (db.formats(book_id) or ()):
                        db.remove_formats({book_id: {'ORIGINAL_EPUB'}})
                    if not db.add_format(book_id, 'EPUB', BytesIO(new), replace=True):
                        raise ValueError('Calibre could not save the scrubbed EPUB')
                    changed.append(book_id)
                else:
                    unchanged += 1
                self.scrub_fields(db, book_id, matcher)
            except Exception as exc:
                errors.append(f'{book_id}: {exc}')
        self.gui.library_view.model().refresh()
        self.gui.tags_view.recount()
        info_dialog(self.gui, 'EPUB Promo Scrubber',
                    f'{len(changed)} EPUB(s) scrubbed; {unchanged} had nothing to remove; {len(errors)} error(s).' +
                    (f'\n{"; ".join(errors)}' if errors else ''), show=True)

    def scrub_fields(self, db, book_id, matcher):
        """Remove the same marks from the library's own title, publisher and comments fields."""
        mi = db.get_metadata(book_id)
        for field, value in (('title', mi.title), ('publisher', mi.publisher), ('comments', mi.comments)):
            if value and matcher.hit(value):
                new = tidy(matcher.clean_text(value))
                if field == 'title' and not new:
                    continue
                db.set_field(field, {book_id: new or None})

    def scrub_folder(self):
        from qt.core import QMessageBox
        choice = QMessageBox.question(self.gui, 'EPUB Promo Scrubber', 'Scrub a whole folder? Choose No to pick a single EPUB file.')
        if choice == QMessageBox.StandardButton.Yes:
            source = QFileDialog.getExistingDirectory(self.gui, 'Select folder containing EPUB files')
        else:
            source, _ = QFileDialog.getOpenFileName(self.gui, 'Select EPUB file', '', 'EPUB (*.epub)')
        if not source:
            return
        in_place = prefs['in_place']
        output = None
        if in_place:
            sure = QMessageBox.question(self.gui, 'Replace original files?',
                                        'Cleaned versions will overwrite the original EPUB files and the originals cannot be recovered. Continue?')
            if sure != QMessageBox.StandardButton.Yes:
                return
        else:
            output = QFileDialog.getExistingDirectory(self.gui, 'Select a separate folder for scrubbed copies')
            if not output:
                return
        try:
            extra, heuristic, drop = self.options()
            rows, report_path = scrub_files(source, output, extra, heuristic, drop, in_place)
            done = 'replaced' if in_place else 'scrubbed'
            counts = {s: sum(r['status'] == s for r in rows) for s in (done, 'unchanged', 'error')}
            info_dialog(self.gui, 'EPUB Promo Scrubber',
                        f'{counts[done]} {done}, {counts["unchanged"]} unchanged, {counts["error"]} errors.\n' +
                        ('Original files were overwritten.' if in_place else 'Originals were not modified.') + f'\nReport: {report_path}', show=True)
        except Exception as exc:
            error_dialog(self.gui, 'EPUB Promo Scrubber failed', str(exc), show=True)
