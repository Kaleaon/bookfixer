"""Import recovered formats through Calibre's database and metadata readers."""
from pathlib import Path

def import_books(gui, rows):
    from calibre.ebooks.metadata.meta import get_metadata
    from calibre.ebooks.metadata.book.base import Metadata
    from calibre.utils.date import parse_date
    db = gui.current_db.new_api
    imported, errors = [], []
    seen = set()
    for row in rows:
        filename = row.get('output')
        if not filename or filename in seen:
            continue
        seen.add(filename)
        book_id = None
        try:
            path = Path(filename)
            fmt = row['format']
            fallback = Path(row['source'].replace('\\', '/')).stem
            try:
                with path.open('rb') as stream:
                    mi = get_metadata(stream, stream_type=fmt)
            except Exception:
                mi = Metadata(fallback, ['Unknown'])
            if not mi.title or mi.title.lower() in ('unknown', 'untitled'):
                mi.title = fallback
            sidecar = row.get('metadata') or {}
            title = sidecar.get('title')
            if isinstance(title, str) and title.strip():
                mi.title = title.strip()
            authors = sidecar.get('authors', sidecar.get('author'))
            if isinstance(authors, str):
                authors = [authors]
            if isinstance(authors, list) and all(isinstance(x, str) for x in authors) and authors:
                mi.authors = authors
            for key, field in [('publisher', 'publisher'), ('description', 'comments')]:
                if isinstance(sidecar.get(key), str):
                    setattr(mi, field, sidecar[key])
            if isinstance(sidecar.get('language'), str):
                mi.languages = [sidecar['language']]
            categories = sidecar.get('categories')
            if isinstance(categories, list) and all(isinstance(x, str) for x in categories):
                mi.tags = categories
            if isinstance(sidecar.get('publishedDate'), str):
                try:
                    mi.pubdate = parse_date(sidecar['publishedDate'], assume_utc=True)
                except Exception:
                    pass
            if isinstance(sidecar.get('isbn'), str):
                mi.set_identifier('isbn', sidecar['isbn'])
            identifiers = sidecar.get('industryIdentifiers', [])
            if isinstance(identifiers, list):
                for identifier in identifiers:
                    if isinstance(identifier, dict) and str(identifier.get('type', '')).startswith('ISBN') and isinstance(identifier.get('identifier'), str):
                        mi.set_identifier('isbn', identifier['identifier'])
            # Compare complete format bytes to avoid importing the same recovery twice.
            duplicate = False
            for existing_id in db.all_book_ids():
                if str(db.field_for('title', existing_id, '')).casefold() != mi.title.casefold():
                    continue
                existing = db.format(existing_id, fmt.upper())
                if existing is not None and existing == path.read_bytes():
                    duplicate = True
                    break
            if duplicate:
                row['import_status'] = 'duplicate skipped'
                continue
            book_id = db.create_book_entry(mi)
            if book_id is None:
                raise ValueError('Calibre did not create a library entry')
            with path.open('rb') as stream:
                if not db.add_format(book_id, fmt.upper(), stream):
                    raise ValueError('Calibre did not save the book format')
            cover = getattr(mi, 'cover_data', None)
            if cover and cover[1]:
                db.set_cover({book_id: cover[1]})
            row.update(import_status='imported', calibre_id=book_id)
            imported.append(book_id)
        except Exception as e:
            # Remove only the incomplete new record created by this import.
            if book_id is not None:
                try:
                    db.remove_books({book_id})
                except Exception as cleanup:
                    row['cleanup_error'] = str(cleanup)
            row.update(import_status='error', import_error=str(e))
            errors.append(f"{row['source']}: {e}")
    if imported:
        gui.library_view.model().refresh()
        gui.tags_view.recount()
    return imported, errors
