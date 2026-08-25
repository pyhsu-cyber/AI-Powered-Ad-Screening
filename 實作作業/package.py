# -*- coding: utf-8 -*-
"""把目前的程式打包成 版本封存/違規廣告快篩_v{N}.zip。

為什麼要有這支腳本：v8 的 GitHub Release 附件曾經把 SPEC/課堂練習/ 帶到公開網路上。
那份資料被 .gitignore 擋在 repo 之外，但手動打包的 zip 是另一條沒人守的路。
所以排除清單寫死在這裡，打包完會再複驗一次，確認機敏檔案沒混進去。

用法：
    python package.py 10          # 產生 違規廣告快篩_v10.zip
    python package.py 10 --force  # 覆蓋已存在的同名檔
"""
import io
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE = os.path.join(ROOT, '版本封存')

# 一律不進封存檔。前三項是機敏／私人資料，其餘是雜物或會讓檔案暴增的東西。
EXCLUDE_DIRS = {
    '課堂練習',      # 成本規劃、SWOT、商業模式圖——明確不對外
    '版本封存',      # 不要把封存檔包進封存檔
    '.git', '.kiro', '__pycache__', 'node_modules', '.vscode',
}
EXCLUDE_FILES = {'api_key.txt', '.env', 'ghauth.log'}
EXCLUDE_EXT = {'.pyc', '.pyo', '.log', '.tmp'}

# 打包後複驗用：檔名裡出現這些字就是有東西漏進去了
FORBIDDEN = ('課堂練習', 'api_key', '.env', 'sk-ant-')


def should_skip(rel):
    parts = rel.replace('\\', '/').split('/')
    if any(p in EXCLUDE_DIRS for p in parts):
        return True
    if parts[-1] in EXCLUDE_FILES:
        return True
    return os.path.splitext(parts[-1])[1].lower() in EXCLUDE_EXT


def main():
    if len(sys.argv) < 2 or not sys.argv[1].isdigit():
        raise SystemExit('用法：python package.py <版本號>  例如 python package.py 10')
    ver = sys.argv[1]
    name = '違規廣告快篩_v%s' % ver
    out = os.path.join(ARCHIVE, name + '.zip')

    if os.path.exists(out) and '--force' not in sys.argv:
        raise SystemExit('%s 已存在。要覆蓋請加 --force' % os.path.basename(out))
    if not os.path.isdir(ARCHIVE):
        os.makedirs(ARCHIVE)

    files, skipped = [], 0
    for base, dirs, fs in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in fs:
            full = os.path.join(base, f)
            rel = os.path.relpath(full, ROOT)
            if should_skip(rel):
                skipped += 1
                continue
            files.append((full, rel))

    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for full, rel in sorted(files, key=lambda x: x[1]):
            z.write(full, os.path.join(name, rel))

    # 複驗：排除清單漏了什麼，這裡要擋下來，不能等到上傳才發現
    with zipfile.ZipFile(out) as z:
        inner = z.namelist()
    leaked = [n for n in inner if any(b in n for b in FORBIDDEN)]
    if leaked:
        os.remove(out)
        raise SystemExit('封存檔含機敏資料，已刪除未產出：\n  ' + '\n  '.join(leaked[:10]))

    mb = os.path.getsize(out) / 1048576.0
    print('%s  %d 項 / %.1f MB' % (os.path.basename(out), len(inner), mb))
    print('  已排除 %d 個檔案（機敏資料、快取、封存檔本身）' % skipped)
    print('  複驗通過：無課堂練習、無金鑰檔')


if __name__ == '__main__':
    main()
