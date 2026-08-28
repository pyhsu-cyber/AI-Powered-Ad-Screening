"""
tests/test_ocr_filter.py — OCR 幻覺行濾除

tesseract 偶爾會對同一塊區域吐出兩個互相競爭的行假設：一個正確、一個完全憑空，
而 data.text 會把兩個都印出來。使用者實際回報過兩次：

  「3繼下台夫愧全」  合法2_食品_穀物飲   conf 0，壓在 conf 91 的「台灣黑豆穀物飲」上
  「可寺咆合」        R6_合法食品_附件一   conf 0，壓在 conf 0 的「黑豆玥物飲」上

判別訊號是**重疊**不是信心值 —— 實測有一批真實內容的信心也很低
（SPF50+PA++++ 只有 7、「延年益壽、青春永凡」只有 18），砍掉會漏抓違規。

夾具 fixtures_ocr_lines.json 是真實 tesseract.js 對測試圖的逐行輸出，
錄下來讓這支測試不必真的跑 OCR（不需要網路、不需要下載 8 MB 語言模型）。

執行方式：
  python tests/test_ocr_filter.py
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.join(os.path.dirname(__file__), '..')
_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        print("  PASS  " + label)
        _passed += 1
    else:
        print("  FAIL  " + label + (("  [" + detail + "]") if detail else ""))
        _failed += 1


def info(label, detail=""):
    print("  INFO  " + label + (("  [" + detail + "]") if detail else ""))


fx = json.loads(io.open(os.path.join(os.path.dirname(__file__), 'fixtures_ocr_lines.json'),
                        encoding='utf-8').read())
reg = json.loads(io.open(os.path.join(ROOT, 'regulations.json'), encoding='utf-8').read())
built = io.open(os.path.join(ROOT, 'static', 'index.html'), encoding='utf-8').read()

# 這三行是確認過的幻覺：圖上完全沒有這些字
PHANTOMS = {
    '合法2_食品_穀物飲.png': ['3繼下台夫愧全'],
    'R1_關捷挺固立_罰1124萬.png': ['Le朵'],
    'R6_合法食品_附件一用語.png': ['可寺咆合'],
}
# 這些是信心很低、但真的存在於圖上的內容，絕對不能被丟掉
LOW_BUT_REAL = {
    '合法3_化粧品_防曬.png': 'SPF50+PA++++',
    '違法3_食品_漢方誇大.png': '延年益壽、青春永凡',
    'R2_苦瓜胜肽_高雄114年.png': '苦瓜勝采複方膠囊',
    'R6_合法食品_附件一用語.png': '黑豆玥物飲',
}

print("── 夾具與出貨檔 ──")
check("夾具有錄到圖", len(fx.get('images', {})) >= 6, str(len(fx.get('images', {}))))
check("夾具有註明引擎與錄製日期", bool(fx.get('_engine')) and bool(fx.get('_recorded')))
check("出貨檔含幻覺行濾除", 'textWithoutPhantomLines' in built)
check("濾除參數齊全（含信心相當時的面積判別）",
      all(k in built for k in ('PHANTOM_MIN_OVERLAP', 'PHANTOM_MIN_GAP', 'PHANTOM_MAX_CONF',
                               'PHANTOM_TIE_CONF', 'PHANTOM_AREA_RATIO')))

for name, ph in PHANTOMS.items():
    lines = fx['images'].get(name, [])
    for p in ph:
        rec = next((l for l in lines if l['text'].replace(' ', '') == p), None)
        check("夾具裡有 %s 的幻覺行 %r" % (name.split('_')[0], p), rec is not None)

print("\n── 濾除行為（用 node 跑出貨產物裡的程式碼）──")
_node = shutil.which('node')
if not _node:
    info("找不到 node，略過濾除行為測試", "夾具與出貨檔檢查不受影響")
else:
    _harness = r'''
const fs = require('fs');
const js = fs.readFileSync(process.argv[2], 'utf8').match(/<script>([\s\S]*)<\/script>/)[1];
const grab = n => { const i = js.indexOf('function ' + n + '('); if (i < 0) throw new Error(n);
  let d = 0, s = false;
  for (let j = i; j < js.length; j++) { if (js[j] === '{') { d++; s = true; }
    else if (js[j] === '}') { d--; if (s && !d) return js.slice(i, j + 1); } } };
const ctx = {};
new Function('g',
  js.match(/const PHANTOM_MIN_OVERLAP[\s\S]*?const PHANTOM_AREA_RATIO\s*=\s*\d+;/)[0] +
  grab('bboxArea') + grab('bboxOverlap') + grab('textWithoutPhantomLines') +
  '\ng.f = textWithoutPhantomLines;')(ctx);
const A = JSON.parse(process.argv[3]);
const clean = s => (s || '').replace(/\s+/g, '');
const out = [];
const t = (l, c, x) => out.push([l, !!c, x || '']);
for (const [name, lines] of Object.entries(A.images)) {
  const data = { lines: lines, text: lines.map(l => l.text).join('\n') };
  const kept = clean(ctx.f(data));
  for (const p of (A.phantoms[name] || []))
    t('丟掉幻覺行　' + name.split('_')[0] + ' ' + JSON.stringify(p), !kept.includes(clean(p)));
  if (A.lowReal[name])
    t('保留低信心但真實的　' + name.split('_')[0] + ' ' + JSON.stringify(A.lowReal[name]),
      kept.includes(clean(A.lowReal[name])));
  // 關鍵字不能因為濾除而消失
  const raw = clean(lines.map(l => l.text).join('\n'));
  const lost = A.kw.filter(k => raw.includes(k) && !kept.includes(k));
  t('關鍵字沒有因濾除而消失　' + name.split('_')[0], lost.length === 0, JSON.stringify(lost));
}
// 邊界
t('拿不到 lines 就原樣回傳（不能反而少讀）', ctx.f({ text: 'abc\ndef' }) === 'abc\ndef');
t('只有一行就算 conf=0 也保留',
  ctx.f({ lines: [{ text: 'x', confidence: 0, bbox: {x0:0,y0:0,x1:9,y1:9} }], text: 'x' }) === 'x');
t('null 輸入不會爆', ctx.f(null) === '');
const twoCol = { lines: [
  { text: '左欄', confidence: 10, bbox: {x0:0,   y0:100, x1:200, y1:130} },
  { text: '右欄', confidence: 95, bbox: {x0:400, y0:100, x1:600, y1:130} }] };
twoCol.text = '左欄\n右欄';
t('雙欄排版（同 y 不同 x）不會誤殺低信心那欄', ctx.f(twoCol).includes('左欄'));
const midGap = { lines: [
  { text: 'A', confidence: 25, bbox: {x0:0, y0:0, x1:100, y1:30} },
  { text: 'B', confidence: 50, bbox: {x0:0, y0:0, x1:300, y1:90} }] };
midGap.text = 'A\nB';
t('信心差中等（25，未達 40 也超過相當範圍）→ 兩個都留', ctx.f(midGap).includes('A'));
console.log(JSON.stringify(out));
'''
    _f = tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8')
    _f.write(_harness)
    _f.close()
    try:
        _kw = reg['demo_keywords']['medical_efficacy'] + reg['demo_keywords']['exaggeration']
        _args = json.dumps({'images': fx['images'], 'phantoms': PHANTOMS,
                            'lowReal': LOW_BUT_REAL, 'kw': _kw}, ensure_ascii=False)
        _p = subprocess.run([_node, _f.name, os.path.join(ROOT, 'static', 'index.html'), _args],
                            capture_output=True, text=True, encoding='utf-8', timeout=60)
        if _p.returncode != 0:
            check("node 測試執行成功", False, (_p.stderr or '')[:200].replace('\n', ' '))
        else:
            for _label, _ok, _detail in json.loads(_p.stdout.strip().split('\n')[-1]):
                check(_label, _ok, _detail)
    finally:
        os.unlink(_f.name)

print("\n" + "=" * 50)
print("OCR 幻覺行濾除測試結果：%d 通過 / %d 失敗" % (_passed, _failed))
# 直接執行時用結束碼回報失敗。pytest 下不能 exit —— 那會變成 collection
# error 而不是一筆乾淨的測試失敗，下面的 test_all_checks_passed 會接手。
if _failed and "pytest" not in sys.modules:
    sys.exit(1)


# ══════════════════════════════════════════════════════════
# pytest 進入點
# ══════════════════════════════════════════════════════════
def test_all_checks_passed():
    """模組層的檢查在 import 時已跑完，這裡把失敗數斷言出來。"""
    assert _failed == 0, f"{_failed} 項檢查失敗（詳見上方 FAIL 行）"
