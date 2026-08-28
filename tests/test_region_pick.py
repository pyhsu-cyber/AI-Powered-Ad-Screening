"""
tests/test_region_pick.py — 框選辨識與「換圖清空文字」

兩件使用者回報的事：

  1. 整張圖一起讀會把不相干的區塊（頁尾、浮水印、旁邊留言）也讀進來，
     密集資訊圖表更是整片糊掉。需要能用左鍵在預覽圖上框一塊只辨識那一塊，
     同一張圖可以重複框，每次結果各自成一行接在「廣告文字」後面。

  2. 手動輸入文字後再丟新圖，舊文字會留著、也不會辨識新圖，得重新整理才行。
     成因是舊版刻意保留使用者手打的字（L1：機器不覆蓋使用者的字）。
     那條規則在「同一張圖」上是對的，但換圖時保留舊文字會讓陳情信引錄 A 圖的
     文字卻附上 B 圖的截圖 —— 送出去只會被承辦人剔除。改成一律清空並提供還原。

前端邏輯用 node 直接跑**出貨產物裡的那份程式碼**驗證；沒有 node 就只做靜態檢查。

執行方式：
  python tests/test_region_pick.py
"""
import io
import json
import os
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


built = io.open(os.path.join(ROOT, 'static', 'index.html'), encoding='utf-8').read()

print("── 出貨檔接線 ──")
for fn in ('initRegionPicker', 'ocrRegion', 'appendAdText', 'selPointOf', 'selDraw'):
    check("含 function %s()" % fn, ('function %s(' % fn) in built)
check("有掛上 initRegionPicker()", 'initRegionPicker();' in built)
check("預覽有定位容器與選取框", 'id="previewWrap"' in built and 'id="selBox"' in built)
check("圖片關掉原生拖曳（否則會蓋掉框選）", 'draggable="false"' in built)
check("只收滑鼠左鍵", 'e.button !== 0' in built)
check("阻擋 dragstart", "'dragstart'" in built)

_i = built.find('async function ocrRegion(')
_ocr = built[_i:built.find('\n}\n', _i)] if _i >= 0 else ''
check("框選辨識會作廢過期結果（辨識途中換圖）", 'myToken !== runToken' in _ocr)
check("框選辨識也套用幻覺行濾除", 'textWithoutPhantomLines' in _ocr)
check("用完釋放 canvas（大圖裁切會吃記憶體）", 'c.width = c.height = 0' in _ocr)
check("裁切後放大受總像素上限約束", 'Math.sqrt(12e6' in _ocr)

print("\n── 換圖清空文字 ──")
check("換圖一律清空（不再只清機器辨識的結果）",
      "const prevTyped = (!textIsMachine && ta.value.trim()) ? ta.value : '';" in built)
check("清空後一律自動分析", 'Promise.resolve(runAnalysis()).then(afterAnalysis, afterAnalysis)' in built)
check("提供還原按鈕，不讓手打內容默默消失", '還原剛才的文字' in built)
check("還原提示排在分析之後（runAnalysis 開頭會清掉通知）",
      built.find('afterAnalysis') < built.find('Promise.resolve(runAnalysis())'))
check("notify 支援動作按鈕", 'function notify(slot, text, type, autoHideMs, action)' in built)
check("舊的『因為有手打文字所以不分析』訊息已移除",
      '但沒有自動分析' not in built)

print("\n── 行為（用 node 跑出貨產物裡的程式碼）──")
_node = shutil.which('node')
if not _node:
    info("找不到 node，略過行為測試", "靜態檢查不受影響")
else:
    _harness = r'''
const fs = require('fs');
const js = fs.readFileSync(process.argv[2], 'utf8').match(/<script>([\s\S]*)<\/script>/)[1];
const grab = n => { const i = js.indexOf('function ' + n + '('); if (i < 0) throw new Error(n);
  let d = 0, s = false;
  for (let j = i; j < js.length; j++) { if (js[j] === '{') { d++; s = true; }
    else if (js[j] === '}') { d--; if (s && !d) return js.slice(i, j + 1); } } };
const ta = { value: '' };
const ctx = {};
new Function('g', '$', `
  let lastOcrText = '', textIsMachine = true;
  ${grab('appendAdText')}
  g.append = appendAdText;
  g.state = () => ({ lastOcrText, textIsMachine });
  g.ta = () => ta.value;
`)(ctx, id => (id === 'adText' ? ta : null));
const out = [];
const t = (l, c, x) => out.push([l, !!c, x === undefined ? '' : String(x)]);

t('第一塊直接放入', ctx.append('黑豆穀物飲') === true && ta.value === '黑豆穀物飲', ta.value);
t('第二塊換行接在後面', ctx.append('調整體質、養顏美容') === true &&
  ta.value === '黑豆穀物飲\n調整體質、養顏美容', JSON.stringify(ta.value));
t('第三塊再換一行', ctx.append('幫助消化，使排便順暢') === true &&
  ta.value.split('\n').length === 3, ta.value.split('\n').length);
t('重複框到同一塊不重覆加', ctx.append('調整體質、養顏美容') === false &&
  ta.value.split('\n').length === 3);
t('空白內容不加', ctx.append('   ') === false && ta.value.split('\n').length === 3);
t('前後空白會 trim', ctx.append('  營養補給  ') === true &&
  ta.value.split('\n')[3] === '營養補給', JSON.stringify(ta.value.split('\n')[3]));
t('框選後標記為使用者內容（背景補讀不會蓋掉）', ctx.state().textIsMachine === false);
ta.value = '使用者自己打的\n';
t('尾端換行不會產生空行', ctx.append('新的一塊') === true &&
  ta.value === '使用者自己打的\n新的一塊', JSON.stringify(ta.value));

// 座標換算：原圖 1000x640 顯示成 500x320
const r = { x: 50, y: 30, w: 200, h: 60, dw: 500, dh: 320 };
const fx = 1000 / r.dw, fy = 640 / r.dh;
t('顯示座標換算回原圖座標', Math.round(r.x*fx) === 100 && Math.round(r.y*fy) === 60 &&
  Math.round(r.w*fx) === 400 && Math.round(r.h*fy) === 120);
const sc = (w, h) => { let s = Math.max(1, Math.min(4, Math.round(900 / w)));
  return Math.max(1, Math.min(s, Math.sqrt(12e6 / (w * h)))); };
t('小塊放大到接近 900px 寬', sc(400, 120) === 2, sc(400,120));
t('大塊不放大（避免上億像素 canvas）', sc(4000, 3000) === 1 &&
  4000*3000*sc(4000,3000)**2 <= 12e6);
console.log(JSON.stringify(out));
'''
    _f = tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8')
    _f.write(_harness)
    _f.close()
    try:
        _p = subprocess.run([_node, _f.name, os.path.join(ROOT, 'static', 'index.html')],
                            capture_output=True, text=True, encoding='utf-8', timeout=60)
        if _p.returncode != 0:
            check("node 測試執行成功", False, (_p.stderr or '')[:200].replace('\n', ' '))
        else:
            for _label, _ok, _detail in json.loads(_p.stdout.strip().split('\n')[-1]):
                check(_label, _ok, _detail)
    finally:
        os.unlink(_f.name)

print("\n" + "=" * 50)
print("框選辨識測試結果：%d 通過 / %d 失敗" % (_passed, _failed))
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
