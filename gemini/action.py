import os

from calibre.gui2 import error_dialog, info_dialog, question_dialog
from calibre.gui2.actions import InterfaceAction
from qt.core import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                     QRadioButton, QSpinBox, Qt, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from calibre_plugins.gemini_library_fixer import engine
from calibre_plugins.gemini_library_fixer.config import prefs
from calibre_plugins.gemini_library_fixer.guikit import run_task

FIELD_LABELS = [('title', 'Titles'), ('authors', 'Authors'), ('series', 'Series and volume number'), ('tags', 'Tags'),
                ('language', 'Language (only if empty)')]
SHOW = {'title': 'Title', 'authors': 'Authors', 'series': 'Series', 'tags': 'Tags', 'language': 'Language'}
PRIVACY = ('Your API key is stored unencrypted in Calibre\'s settings folder. Only book details (title, authors, series, tags, '
           'publisher, language, file names) are sent to Google; the opening text of a book is sent only if you tick that option. '
           'Changing a title or author also renames the book\'s folder and files in your library. Nothing changes until you press Apply.')


def show_value(field, value):
    if field == 'series':
        name, index = value
        return f'{name} #{index:g}' if name and index is not None else (name or '(none)')
    if isinstance(value, list):
        return ', '.join(value) if value else '(none)'
    return value or '(none)'


class GeminiFixerAction(InterfaceAction):
    name = 'Gemini Library Fixer'
    action_spec = ('Gemini fix books', None, 'Rename, sort and fix book metadata with the Google Gemini API', None)

    def genesis(self):
        self.qaction.triggered.connect(self.show_dialog)

    # -- reading and writing the library ------------------------------------------------------------------------------
    def books_for(self, ids, with_excerpt):
        db = self.gui.current_db.new_api
        books = []
        for i, book_id in enumerate(ids):
            mi = db.get_metadata(book_id, get_cover=False)
            fmts = list(db.formats(book_id) or [])
            names = []
            for fmt in fmts:
                path = db.format_abspath(book_id, fmt)
                if path:
                    names.append(os.path.basename(path))
            excerpt = ''
            if with_excerpt and 'EPUB' in fmts:
                excerpt = engine.epub_excerpt(db.format_abspath(book_id, 'EPUB'))
            books.append({'id': book_id, 'title': mi.title or '', 'authors': list(mi.authors or []),
                          'series': mi.series or '', 'series_index': mi.series_index if mi.series else None,
                          'tags': list(mi.tags or []), 'languages': list(mi.languages or []), 'publisher': mi.publisher or '',
                          'filenames': names, 'excerpt': excerpt})
            if i % 50 == 0:
                QApplication.processEvents()
        return books

    def write_changes(self, items):
        """items: [(book_id, {field: (old, new)})]. Returns (changed_ids, errors, undo)."""
        db = self.gui.current_db.new_api
        done, errors, undo = [], [], {}
        for book_id, changes in items:
            saved = {}
            try:
                for field, (old, new) in changes.items():
                    if field == 'title':
                        db.set_field('title', {book_id: new})
                    elif field == 'authors':
                        db.set_field('authors', {book_id: tuple(new)})
                    elif field == 'series':
                        db.set_field('series', {book_id: new[0]})
                        db.set_field('series_index', {book_id: new[1]})
                    elif field == 'tags':
                        db.set_field('tags', {book_id: tuple(new)})
                    elif field == 'language':
                        db.set_field('languages', {book_id: tuple(new)})
                    saved[field] = [old[0], old[1]] if field == 'series' else old
                done.append(book_id)
            except Exception as exc:
                errors.append(f'{changes.get("title", ("", ""))[0] or book_id}: {exc}')
            if saved:
                undo[str(book_id)] = saved
        return done, errors, undo

    def restore(self, undo):
        db = self.gui.current_db.new_api
        done, errors = [], []
        for key, saved in undo.items():
            book_id = int(key)
            try:
                if not db.has_id(book_id):
                    continue
                for field, old in saved.items():
                    if field == 'title':
                        db.set_field('title', {book_id: old})
                    elif field == 'authors':
                        db.set_field('authors', {book_id: tuple(old)})
                    elif field == 'series':
                        db.set_field('series', {book_id: old[0] or None})
                        if old[0] and old[1] is not None:
                            db.set_field('series_index', {book_id: old[1]})
                    elif field == 'tags':
                        db.set_field('tags', {book_id: tuple(old)})
                    elif field == 'language':
                        db.set_field('languages', {book_id: tuple(old)})
                done.append(book_id)
            except Exception as exc:
                errors.append(f'book {book_id}: {exc}')
        return done, errors

    def refresh(self, ids):
        if ids:
            self.gui.library_view.model().refresh_ids(ids)
            self.gui.tags_view.recount()

    # -- the window ---------------------------------------------------------------------------------------------------
    def show_dialog(self):
        selected = list(self.gui.library_view.get_selected_ids())
        dialog = QDialog(self.gui)
        dialog.setWindowTitle('Gemini Library Fixer')
        dialog.resize(820, 760)
        layout = QVBoxLayout(dialog)
        note = QLabel(PRIVACY)
        note.setWordWrap(True)
        layout.addWidget(note)

        scope_selected = QRadioButton(f'Selected books ({len(selected)})')
        scope_all = QRadioButton('Entire library (uses many requests; start with a few selected books)')
        (scope_selected if selected else scope_all).setChecked(True)
        scope_selected.setEnabled(bool(selected))
        layout.addWidget(scope_selected)
        layout.addWidget(scope_all)

        row = QHBoxLayout()
        row.addWidget(QLabel('Google AI API key:'))
        key = QLineEdit(prefs['api_key'])
        key.setEchoMode(QLineEdit.EchoMode.Password)
        key.setPlaceholderText('From https://aistudio.google.com/apikey  (or set GEMINI_API_KEY)')
        row.addWidget(key, 1)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel('Model:'))
        model = QComboBox()
        model.setEditable(True)
        model.addItem(prefs['model'])
        model.setCurrentText(prefs['model'])
        row.addWidget(model, 1)
        models_btn = QPushButton('List models')
        models_btn.setToolTip('Ask Google which models your key can use')
        row.addWidget(models_btn)
        layout.addLayout(row)

        layout.addWidget(QLabel('Fix:'))
        boxes = {}
        for field, label in FIELD_LABELS:
            boxes[field] = QCheckBox(label)
            boxes[field].setChecked(field in prefs['fields'])
            layout.addWidget(boxes[field])
        tags_remove = QCheckBox('Let it remove or rename existing tags (otherwise it can only add tags)')
        tags_remove.setChecked(bool(prefs['tags_remove']))
        layout.addWidget(tags_remove)
        excerpt = QCheckBox('Also send the first ~1500 characters of each EPUB (helps with badly named books; sends book text to Google)')
        excerpt.setChecked(bool(prefs['excerpt']))
        layout.addWidget(excerpt)
        row = QHBoxLayout()
        row.addWidget(QLabel('Minimum confidence:'))
        confidence = QComboBox()
        confidence.addItems(['low', 'medium', 'high'])
        confidence.setCurrentText(prefs['min_confidence'])
        row.addWidget(confidence)
        row.addWidget(QLabel('Books per request:'))
        batch = QSpinBox()
        batch.setRange(1, 50)
        batch.setValue(int(prefs['batch_size']))
        row.addWidget(batch)
        row.addStretch(1)
        layout.addLayout(row)

        tree = QTreeWidget()
        tree.setHeaderLabels(['Suggested change', 'Why'])
        tree.setColumnWidth(0, 520)
        layout.addWidget(tree, 1)
        status = QLabel('Press Check books to ask Gemini. Big changes (a very different title or author) are left unticked.')
        status.setWordWrap(True)
        layout.addWidget(status)

        buttons = QDialogButtonBox()
        check_btn = QPushButton('Check books')
        apply_btn = QPushButton('Apply ticked changes')
        apply_btn.setEnabled(False)
        undo_btn = QPushButton('Undo last run')
        undo_btn.setEnabled(bool(prefs['undo']))
        buttons.addButton(check_btn, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(apply_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(undo_btn, QDialogButtonBox.ButtonRole.ResetRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        def api_key():
            return key.text().strip() or os.environ.get('GEMINI_API_KEY', '') or os.environ.get('GOOGLE_API_KEY', '')

        def chosen_fields():
            return tuple(f for f, _ in FIELD_LABELS if boxes[f].isChecked())

        def save_prefs():
            prefs['api_key'] = key.text().strip()
            prefs['model'] = model.currentText().strip() or engine.DEFAULT_MODEL
            prefs['fields'] = list(chosen_fields())
            prefs['tags_remove'] = tags_remove.isChecked()
            prefs['excerpt'] = excerpt.isChecked()
            prefs['min_confidence'] = confidence.currentText()
            prefs['batch_size'] = batch.value()

        def do_list_models():
            save_prefs()
            if not api_key():
                return error_dialog(dialog, 'Gemini', 'Enter your API key first.', show=True)
            task = run_task(dialog, 'Asking Google for the model list…', lambda t: engine.list_models(api_key(), cancelled=t.cancelled))
            if task.error:
                return error_dialog(dialog, 'Gemini', str(task.error), show=True)
            if task.result:
                current = model.currentText()
                model.clear()
                model.addItems(task.result)
                model.setCurrentText(current)

        def do_check():
            save_prefs()
            if not api_key():
                return error_dialog(dialog, 'Gemini', 'Enter your Google AI API key first.', show=True)
            if not chosen_fields():
                return error_dialog(dialog, 'Gemini', 'Tick at least one thing to fix.', show=True)
            ids = selected if scope_selected.isChecked() else sorted(self.gui.current_db.new_api.all_book_ids())
            if len(ids) > 100 and not question_dialog(dialog, 'Gemini', f'{len(ids)} books will be sent to Google in batches of {batch.value()}. Continue?'):
                return
            books = self.books_for(ids, excerpt.isChecked())
            task = run_task(dialog, 'Asking Gemini…', lambda t: engine.plan_fixes(
                books, api_key(), model.currentText().strip() or engine.DEFAULT_MODEL, chosen_fields(), confidence.currentText(),
                batch.value(), tags_remove.isChecked(), progress=lambda text: setattr(t, 'status', text), cancelled=t.cancelled))
            tree.clear()
            apply_btn.setEnabled(False)
            if task.error:
                return error_dialog(dialog, 'Gemini', str(task.error), show=True)
            suggestions, skipped = task.result or ([], [])
            cancelled_note = ' (cancelled early)' if task.cancelled() else ''
            for s in suggestions:
                top = QTreeWidgetItem(tree, [s['title'] or f"book {s['id']}", f"{s['confidence']} confidence" + ('; BIG CHANGE' if s['big'] else '')])
                top.setFlags(top.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                want = Qt.CheckState.Unchecked if s['big'] else Qt.CheckState.Checked  # adding a child resets an auto-tristate parent, so set the parent last
                top.setData(0, Qt.ItemDataRole.UserRole, s['id'])
                for field, (old, new) in s['changes'].items():
                    child = QTreeWidgetItem(top, [f'{SHOW[field]}:  {show_value(field, old)}  →  {show_value(field, new)}', s['reason'] if field == 'title' else ''])
                    child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    child.setCheckState(0, want)
                    child.setData(0, Qt.ItemDataRole.UserRole, field)
                    child.setData(0, Qt.ItemDataRole.UserRole + 1, (old, new))
                top.setCheckState(0, want)
                top.setExpanded(True)
            text = f'{len(suggestions)} of {len(books)} book(s) have suggested changes{cancelled_note}.'
            if skipped:
                text += f' {len(skipped)} could not be checked: ' + '; '.join(skipped[:3]) + (' …' if len(skipped) > 3 else '')
            status.setText(text)
            apply_btn.setEnabled(bool(suggestions))

        def collect():
            items = []
            for i in range(tree.topLevelItemCount()):
                top = tree.topLevelItem(i)
                changes = {}
                for j in range(top.childCount()):
                    child = top.child(j)
                    if child.checkState(0) == Qt.CheckState.Checked:
                        changes[child.data(0, Qt.ItemDataRole.UserRole)] = child.data(0, Qt.ItemDataRole.UserRole + 1)
                if changes:
                    items.append((top.data(0, Qt.ItemDataRole.UserRole), changes))
            return items

        def do_apply():
            items = collect()
            if not items:
                return error_dialog(dialog, 'Gemini', 'Nothing is ticked.', show=True)
            done, errors, undo = self.write_changes(items)
            if undo:
                prefs['undo'] = undo
                undo_btn.setEnabled(True)
            self.refresh(done)
            text = f'Updated {len(done)} book(s). "Undo last run" can put the old values back.'
            if errors:
                text += '\n\nProblems:\n' + '\n'.join(errors[:10])
            info_dialog(self.gui, 'Gemini', text, show=True)
            tree.clear()
            apply_btn.setEnabled(False)

        def do_undo():
            undo = dict(prefs['undo'])
            if not undo or not question_dialog(dialog, 'Gemini', f'Put back the old values for {len(undo)} book(s) changed in the last run?'):
                return
            done, errors = self.restore(undo)
            self.refresh(done)
            if not errors:
                prefs['undo'] = {}
                undo_btn.setEnabled(False)
            text = f'Restored {len(done)} book(s).' + ('\n\nProblems:\n' + '\n'.join(errors[:10]) if errors else '')
            info_dialog(self.gui, 'Gemini', text, show=True)

        key.editingFinished.connect(save_prefs)  # the key is remembered as soon as it is typed, not only after a check
        dialog.finished.connect(lambda _result: save_prefs())
        models_btn.clicked.connect(do_list_models)
        check_btn.clicked.connect(do_check)
        apply_btn.clicked.connect(do_apply)
        undo_btn.clicked.connect(do_undo)
        dialog.exec()
