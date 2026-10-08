import importlib.util
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location('scrub_core', Path(__file__).resolve().parents[1] / 'scrubber_plugin/core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

XHTML = '<?xml version="1.0" encoding="utf-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head><body>%s</body></html>'
CONTAINER = '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
OPF = '''<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>Book Title - OceanofPDF.com</dc:title><dc:publisher>OceanofPDF.com</dc:publisher><dc:creator>An Author</dc:creator></metadata>
<manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="promo" href="promo.xhtml" media-type="application/xhtml+xml"/><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/></manifest>
<spine><itemref idref="promo"/><itemref idref="c1"/></spine></package>'''
NAV = XHTML % '<nav><ol><li><a href="promo.xhtml">Downloaded</a></li><li><a href="c1.xhtml">Chapter 1</a></li></ol></nav>'


def make(chapter, promo='<p>Downloaded from <a href="https://oceanofpdf.com">OceanofPDF.com</a></p>', opf=OPF):
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        z.writestr('mimetype', 'application/epub+zip', zipfile.ZIP_STORED)
        z.writestr('META-INF/container.xml', CONTAINER)
        z.writestr('OEBPS/content.opf', opf)
        z.writestr('OEBPS/nav.xhtml', NAV)
        z.writestr('OEBPS/promo.xhtml', XHTML % promo)
        z.writestr('OEBPS/c1.xhtml', XHTML % chapter)
    return b.getvalue()


def read(data, name):
    return zipfile.ZipFile(io.BytesIO(data)).read(name).decode()


class ScrubTests(unittest.TestCase):
    def test_removes_promo_page_links_and_metadata(self):
        data, report = core.scrub_epub(make('<p>Real story text.</p><p>' + 'The hero walked on. ' * 15 + 'Then she saw <a href="http://www.oceanofpdf.com/x">the old tower</a> ahead.</p>'))
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        self.assertNotIn('OEBPS/promo.xhtml', names)
        self.assertEqual(names[0], 'mimetype')
        self.assertEqual(report['dropped_pages'], ['OEBPS/promo.xhtml'])
        chapter = read(data, 'OEBPS/c1.xhtml')
        self.assertIn('Real story text.', chapter)
        self.assertNotIn('oceanofpdf', chapter.lower())
        self.assertIn('the old tower', chapter)
        opf = read(data, 'OEBPS/content.opf')
        self.assertNotIn('oceanofpdf', opf.lower())
        self.assertNotIn('promo', opf)
        self.assertIn('<dc:title>Book Title</dc:title>', opf)
        self.assertNotIn('promo.xhtml', read(data, 'OEBPS/nav.xhtml'))
        self.assertIn('Chapter 1', read(data, 'OEBPS/nav.xhtml'))

    def test_clean_book_is_unchanged(self):
        clean = OPF.replace(' - OceanofPDF.com', '').replace('OceanofPDF.com', 'Some Press')
        data, report = core.scrub_epub(make('<p>Nothing here.</p>', '<p>Cover page</p>', clean))
        self.assertIsNone(data)
        self.assertEqual(report['changes'], [])

    def test_long_paragraph_keeps_surrounding_text(self):
        text = 'A long paragraph. ' * 30 + 'Found at oceanofpdf.com okay. ' + 'More story. ' * 5
        data, _ = core.scrub_epub(make('<p>%s</p>' % text))
        chapter = read(data, 'OEBPS/c1.xhtml')
        self.assertIn('More story.', chapter)
        self.assertNotIn('oceanofpdf', chapter.lower())

    def test_generic_promo_block_and_toggle(self):
        chapter = '<p>Story.</p><p>Downloaded from www.freebooks-example.net</p>'
        data, _ = core.scrub_epub(make(chapter))
        self.assertNotIn('freebooks-example', read(data, 'OEBPS/c1.xhtml'))
        data, _ = core.scrub_epub(make(chapter), heuristic=False)
        self.assertIn('freebooks-example', read(data, 'OEBPS/c1.xhtml'))

    def test_custom_pattern_and_author_url_kept(self):
        chapter = '<p>See <a href="https://author.example/">the author site</a>.</p><p>Brought by BookBlaster!</p>'
        data, _ = core.scrub_epub(make(chapter), extra_patterns=['BookBlaster'])
        chapter = read(data, 'OEBPS/c1.xhtml')
        self.assertIn('author.example', chapter)
        self.assertNotIn('BookBlaster', chapter)

    def test_not_epub_and_files_api(self):
        with self.assertRaises(ValueError):
            core.scrub_epub(b'not a zip')
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'in'; src.mkdir()
            (src / 'a.epub').write_bytes(make('<p>Hi</p>'))
            rows, report = core.scrub_files(src, Path(d) / 'out')
            self.assertEqual(rows[0]['status'], 'scrubbed')
            self.assertTrue(report.exists())
            self.assertIn(b'OceanofPDF', (src / 'a.epub').read_bytes())


if __name__ == '__main__':
    unittest.main()
