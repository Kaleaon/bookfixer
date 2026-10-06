from pathlib import Path
import zipfile
root = Path(__file__).resolve().parent
with zipfile.ZipFile(root / 'dist/TakeoutBookFixer.zip', 'w', zipfile.ZIP_DEFLATED) as z:
    for path in sorted((root / 'plugin').glob('*.py')):
        z.write(path, path.name)
    z.writestr('plugin-import-name-takeout_book_fixer.txt', '')
print(root / 'dist/TakeoutBookFixer.zip')
