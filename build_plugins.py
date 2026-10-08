"""Build every plugin zip into dist/. Shared modules from common/ are bundled into the plugins that use them."""
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parent
PLUGINS = {
    'MetabodsDownloader.zip': ('metabods', 'metabods_downloader', ['storykit.py', 'guikit.py', 'libkit.py']),
    'NiftyDownloader.zip': ('nifty', 'nifty_downloader', ['storykit.py', 'guikit.py', 'libkit.py']),
    'StoryCollectionTagger.zip': ('tagger', 'story_collection_tagger', []),
}
PLUGINS_BY_IMPORT = [v[1] for v in PLUGINS.values()]


def build_all(dest):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    built = {}
    for zip_name, (folder, import_name, shared) in PLUGINS.items():
        target = dest / zip_name
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
            for path in sorted((root / folder).glob('*.py')):
                z.write(path, path.name)
            for name in shared:
                z.write(root / 'common' / name, name)
            z.writestr(f'plugin-import-name-{import_name}.txt', '')
        built[import_name] = target
    return built


if __name__ == '__main__':
    for target in build_all(root / 'dist').values():
        print(target)
