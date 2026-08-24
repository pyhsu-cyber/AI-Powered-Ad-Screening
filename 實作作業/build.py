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
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'static', 'index.html')

html = io.open(os.path.join(HERE, 'index.html'), encoding='utf-8').read()
css = io.open(os.path.join(HERE, 'styles.css'), encoding='utf-8').read()
js = io.open(os.path.join(HERE, 'app.js'), encoding='utf-8').read()

out, n1 = re.subn(r'<link rel="stylesheet" href="styles\.css">',
                  lambda m: '<style>\n' + css.rstrip() + '\n</style>', html)
# 從 regulations.json 注入法條表與關鍵字品類，避免前端這份副本與資料檔漂移
reg = json.loads(io.open(os.path.join(os.path.dirname(HERE), 'regulations.json'),
                         encoding='utf-8').read())
laws = {l['id']: {k: l[k] for k in ('law_name', 'article', 'summary', 'penalty', 'url')}
        for l in reg['laws']}
scope = reg.get('keyword_scope', {})
block = ('/* @generated-from-regulations\n'
         '   本區塊由 build.py 從 ../regulations.json 自動產生，請不要手改。 */\n'
         'const KEYWORD_SCOPE = ' + json.dumps(
             {'cosmetic_only': scope.get('cosmetic_only', []),
              'food_only': scope.get('food_only', [])},
             ensure_ascii=False, indent=2) + ';\n'
         'const LAWS = ' + json.dumps(laws, ensure_ascii=False, indent=2) + ';\n'
         '/* @end-generated */')
js, nb = re.subn(r'/\* @generated-from-regulations.*?/\* @end-generated \*/',
                 lambda m: block, js, flags=re.S)
if nb != 1:
    raise SystemExit('建置失敗：app.js 裡找不到 @generated-from-regulations 區塊 (%d)' % nb)
print('  已注入 %d 條法條、化粧品專屬 %d 詞、食品專屬 %d 詞'
      % (len(laws), len(scope.get('cosmetic_only', [])), len(scope.get('food_only', []))))

out, n2 = re.subn(r'<script src="app\.js"></script>',
                  lambda m: '<script>\n' + js.rstrip() + '\n</script>', out)

if n1 != 1 or n2 != 1:
    raise SystemExit('建置失敗：index.html 裡找不到 styles.css / app.js 的引用 (%d/%d)' % (n1, n2))

io.open(OUT, 'w', encoding='utf-8', newline='').write(out)
print('建置完成 -> %s  (%d 字元)' % (OUT, len(out)))
print('提醒：改了 regulations.json 要重開程式；只改介面的話重整瀏覽器 Ctrl+F5 即可。')
