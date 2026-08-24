# -*- coding: utf-8 -*-
"""建置：把 實作作業/{index.html, styles.css, app.js} 合併成 ../static/index.html

用法（在本資料夾按住 Shift 右鍵 →「在此處開啟 PowerShell」後執行）：
    python build.py

為什麼要這一步：
    違規廣告快篩.exe 的內建伺服器只服務 "/" 與 "/index.html"，
    /styles.css 與 /app.js 會被回 404，
    所以實際跑的版本必須把 CSS 與 JS 內嵌成單一 HTML 檔。
"""
import io
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'static', 'index.html')

html = io.open(os.path.join(HERE, 'index.html'), encoding='utf-8').read()
css = io.open(os.path.join(HERE, 'styles.css'), encoding='utf-8').read()
js = io.open(os.path.join(HERE, 'app.js'), encoding='utf-8').read()

out, n1 = re.subn(r'<link rel="stylesheet" href="styles\.css">',
                  lambda m: '<style>\n' + css.rstrip() + '\n</style>', html)
out, n2 = re.subn(r'<script src="app\.js"></script>',
                  lambda m: '<script>\n' + js.rstrip() + '\n</script>', out)

if n1 != 1 or n2 != 1:
    raise SystemExit('建置失敗：index.html 裡找不到 styles.css / app.js 的引用 (%d/%d)' % (n1, n2))

io.open(OUT, 'w', encoding='utf-8', newline='').write(out)
print('建置完成 -> %s  (%d 字元)' % (OUT, len(out)))
print('提醒：改了 regulations.json 要重開程式；只改介面的話重整瀏覽器 Ctrl+F5 即可。')
