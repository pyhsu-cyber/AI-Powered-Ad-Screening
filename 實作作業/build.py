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
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'static', 'index.html')

# ── 版號單一來源 ──────────────────────────────────────────
# 版號散落在四份文件裡各寫各的（曾經 UI 沒版號、使用說明寫 v9、說明書寫 v6、
# SPEC 基準寫 v5），使用者回報問題時說不出自己在跑哪一版。改成以根目錄的
# VERSION 檔為唯一來源，這裡注入 UI 並反過來驗證各文件——對不上就建置失敗，
# 免得又漂移。
ROOT_DIR = os.path.dirname(HERE)
VERSION = io.open(os.path.join(ROOT_DIR, 'VERSION'), encoding='utf-8').read().strip()
VTAG = 'v' + VERSION

def _expect(relpath, needle):
    text = io.open(os.path.join(ROOT_DIR, relpath), encoding='utf-8').read()
    if needle not in text:
        raise SystemExit(
            '建置失敗：%s 的版號與 VERSION(%s) 不符，找不到 %r'
            '　　（每次修改都要進版：更新 VERSION 後，這幾處要一起改）'
            % (relpath, VTAG, needle))

_expect('使用說明.txt', 'AI 違規廣告快篩與一鍵通報系統（PoC）  ' + VTAG)
_expect('功能使用說明書.html', '<span class="ver">%s 使用說明書</span>' % VTAG)
_expect('功能使用說明書.html', 'AI 違規廣告快篩與一鍵通報系統 %s　·' % VTAG)
_expect('說明文件/版本紀錄.md', '## %s（現行版本）' % VTAG)
_expect('說明文件/版本紀錄.md', '| **%s** |' % VTAG)

html = io.open(os.path.join(HERE, 'index.html'), encoding='utf-8').read()
css = io.open(os.path.join(HERE, 'styles.css'), encoding='utf-8').read()
js = io.open(os.path.join(HERE, 'app.js'), encoding='utf-8').read()

html, nv = re.subn(r'\{\{VERSION\}\}', lambda m: VTAG, html)
if nv != 1:
    raise SystemExit('建置失敗：index.html 裡找不到 {{VERSION}} 佔位符 (%d)' % nv)

out, n1 = re.subn(r'<link rel="stylesheet" href="styles\.css">',
                  lambda m: '<style>\n' + css.rstrip() + '\n</style>', html)
# 從 regulations.json 注入法條表與關鍵字品類，避免前端這份副本與資料檔漂移
reg = json.loads(io.open(os.path.join(os.path.dirname(HERE), 'regulations.json'),
                         encoding='utf-8').read())
laws = {l['id']: {k: l[k] for k in ('law_name', 'article', 'summary', 'penalty', 'url')}
        for l in reg['laws']}
scope = reg.get('keyword_scope', {})
ev = reg.get('keyword_evidence', {})
block = ('/* @generated-from-regulations\n'
         '   本區塊由 build.py 從 ../regulations.json 自動產生，請不要手改。 */\n'
         'const KEYWORD_SCOPE = ' + json.dumps(
             {'cosmetic_only': scope.get('cosmetic_only', []),
              'food_only': scope.get('food_only', []),
              'drug_only': scope.get('drug_only', [])},
             ensure_ascii=False, indent=2) + ';\n'
         'const KEYWORD_EVIDENCE = ' + json.dumps(
             {'sources': ev.get('sources', []), 'map': ev.get('map', {})},
             ensure_ascii=False, separators=(',', ':')) + ';\n'
         'const PRE_APPROVAL = ' + json.dumps(
             {k: v for k, v in reg.get('pre_approval', {}).items()
              if not k.startswith('_')}, ensure_ascii=False, indent=2) + ';\n'
         'const OUT_OF_SCOPE = ' + json.dumps(
             {k: v for k, v in reg.get('out_of_scope', {}).items()
              if not k.startswith('_')}, ensure_ascii=False, indent=2) + ';\n'
         'const CONTEXT_EXCLUSIONS = ' + json.dumps(
             {k: v for k, v in reg.get('context_exclusions', {}).items()
              if not k.startswith('_')}, ensure_ascii=False, indent=2) + ';\n'
         'const LAWS = ' + json.dumps(laws, ensure_ascii=False, indent=2) + ';\n'
         '/* @end-generated */')
js, nb = re.subn(r'/\* @generated-from-regulations.*?/\* @end-generated \*/',
                 lambda m: block, js, flags=re.S)
if nb != 1:
    raise SystemExit('建置失敗：app.js 裡找不到 @generated-from-regulations 區塊 (%d)' % nb)
evm = ev.get('map', {})
lv = {k: sum(1 for x in evm.values() if x[0] == k) for k in 'coi'}
print('  已注入 %d 條法條、化粧品專屬 %d 詞、食品專屬 %d 詞、藥物專屬 %d 詞'
      % (len(laws), len(scope.get('cosmetic_only', [])),
         len(scope.get('food_only', [])), len(scope.get('drug_only', []))))
print('  證據等級：裁處案例 %d、法規明文 %d、推論（疑似）%d' % (lv['c'], lv['o'], lv['i']))
print('  事前核准制品類：%s'
      % '、'.join(k for k in reg.get('pre_approval', {}) if not k.startswith('_')))
print('  法域外品類：%s'
      % '、'.join(k for k in reg.get('out_of_scope', {}) if not k.startswith('_')))
_ce = reg.get('context_exclusions', {})
print('  語境排除：%d 條規則、%d 個關鍵字、%d 個療效動詞否決詞'
      % (len(_ce.get('rules', [])),
         sum(len(r.get('keywords', [])) for r in _ce.get('rules', [])),
         len(_ce.get('claim_blockers', []))))

out, n2 = re.subn(r'<script src="app\.js"></script>',
                  lambda m: '<script>\n' + js.rstrip() + '\n</script>', out)

if n1 != 1 or n2 != 1:
    raise SystemExit('建置失敗：index.html 裡找不到 styles.css / app.js 的引用 (%d/%d)' % (n1, n2))

io.open(OUT, 'w', encoding='utf-8', newline='').write(out)
print('建置完成 -> %s  (%s, %d 字元)' % (OUT, VTAG, len(out)))

# ── 同時輸出 GitHub Pages 版（純瀏覽器，不需要 exe）
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, 'docs')
os.makedirs(DOCS, exist_ok=True)
io.open(os.path.join(DOCS, 'index.html'), 'w', encoding='utf-8', newline='').write(out)
shutil.copyfile(os.path.join(ROOT, 'regulations.json'),
                os.path.join(DOCS, 'regulations.json'))
io.open(os.path.join(DOCS, '.nojekyll'), 'w', encoding='utf-8').write('')
print('Pages 版 -> %s（含 regulations.json）' % DOCS)
print('提醒：改了 regulations.json 要重開程式；只改介面的話重整瀏覽器 Ctrl+F5 即可。')
