from pathlib import Path
import zipfile
root = Path(__file__).resolve().parent
target = root / 'dist/MetabodsDownloader.zip'
with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
    for path in sorted((root / 'metabods').glob('*.py')):
        z.write(path, path.name)
    z.writestr('plugin-import-name-metabods_downloader.txt', '')
print(target)
