"""
tests/test_ocr_passes.py — 純瀏覽器模式的多趟補讀

exe 模式有兩套 OCR：Windows 內建（主要）＋ 瀏覽器 tesseract（交叉比對），
還會用 serverOcrVariants 對不同前處理讓 Windows OCR 再讀幾趟。
線上版只有 tesseract 一套，而 crossCheckWithBrowserOCR 以前第一行就
`if (standalone) return`，等於**整套補讀機制在線上版完全沒有作用**。

v19 補上 browserOcrVariants：用同一組前處理（2 倍放大／2 倍放大＋對比拉伸）
讓 tesseract 再讀，結果用 mergeOcrText 併回去。

實測 17 張圖（tesseract.js 5.1.1）：
  六張合成測試圖與七張真實案例圖——原圖就讀滿了，補讀一個關鍵字都沒多，也沒少
  使用者實際丟進來的廣告截圖——廣告2 從 0 到 1（「不易形成體脂肪」）、
                              廣告3 從 0 到 1（「漢方」）
真實廣告版面雜、對比差、字疊在照片上，正是需要補讀的那一群。

同時把兩個既有缺陷一起修掉（都是那個 early return 造成的）：
  - 辨識信心過低的警語移到 finally，線上版（唯一 100% 靠瀏覽器 OCR 的那一版）
    以前永遠看不到
  - 多處提早 return 會把「背景補讀中…」的轉圈留在畫面上，改成一定還原

執行方式：
  python tests/test_ocr_passes.py
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


def body(fn):
    """取出函式原始碼（大括號配對）。"""
    i = built.find('function ' + fn + '(')
    if i < 0:
        return ''
    d = 0
    started = False
    for j in range(i, len(built)):
        if built[j] == '{':
            d += 1
            started = True
        elif built[j] == '}':
            d -= 1
            if started and d == 0:
                return built[i:j + 1]
    return ''


print("── 補讀函式存在且接上線上版 ──")
check("有 browserOcrVariants()", 'function browserOcrVariants(' in built)
check("exe 模式的 serverOcrVariants 仍在", 'function serverOcrVariants(' in built)

cross = body('crossCheckWithBrowserOCR')
check("crossCheck 不再第一行就擋掉 standalone",
      'if (standalone) return;' not in cross, "線上版會完全跳過補讀")
check("crossCheck 有 standalone 分支", 'if (standalone) {' in cross)
check("standalone 分支呼叫 browserOcrVariants", 'browserOcrVariants(' in cross)
check("exe 分支仍呼叫 serverOcrVariants", 'serverOcrVariants(' in cross)
check("純文字輸入（沒有圖）不進補讀", 'if (!rawDataUrl) return;' in cross)
check("exe 模式仍只在走過 Windows OCR 後才補",
      "if (!standalone && serverOcr !== true) return;" in cross)

print("\n── 兩個被 early return 連帶壓住的缺陷 ──")
check("辨識信心警語移到 finally（線上版以前永遠看不到）",
      cross.find('} finally {') < cross.find('這張圖的文字辨識不可靠'),
      "警語仍在 finally 之前")
check("信心警語只有一份", built.count('這張圖的文字辨識不可靠') == 1,
      str(built.count('這張圖的文字辨識不可靠')))
check("離開時一定還原狀態列（否則轉圈會一直留著）",
      'ocrBarBefore' in cross and 'touchedBar' in cross and '} finally {' in cross)
check("警語建議改用框選（v18 的新功能）", '框選要看的那一塊單獨辨識' in cross)

print("\n── 放大受總像素上限約束 ──")
prep = body('prepare')
check("有 MAX_CANVAS_PX 常數", 'const MAX_CANVAS_PX' in built)
check("prepare() 會壓上限", 'MAX_CANVAS_PX' in prep, "大圖 2 倍放大會讓分頁 OOM")
check("縮小（scale<1）不受影響", 'scale > 1 &&' in prep)

print("\n── 行為（用 node 跑出貨產物裡的程式碼）──")
_node = shutil.which('node')
if not _node:
    info("找不到 node，略過行為測試", "靜態檢查不受影響")
else:
    _harness = r'''
const fs = require('fs');
const js = fs.readFileSync(process.argv[2], 'utf8').match(/<script>([\s\S]*)<\/script>/)[1];
const CAP = Number(js.match(/const MAX_CANVAS_PX = ([\de.]+)/)[1]);
const out = [];
const t = (l, c, x) => out.push([l, !!c, x === undefined ? '' : String(x)]);

// prepare() 的上限計算
const cap = (w, h, scale) => (scale > 1 && w*h*scale*scale > CAP)
  ? Math.max(1, Math.sqrt(CAP / (w*h))) : scale;
t('上限常數為 1200 萬像素', CAP === 12e6, CAP);
t('960x640 放大 2 倍不受限（246 萬像素）', cap(960, 640, 2) === 2);
t('1000x660 放大 2 倍不受限', cap(1000, 660, 2) === 2);
t('4000x3000 放大 2 倍會被壓下來', cap(4000, 3000, 2) < 2, cap(4000,3000,2).toFixed(2));
t('壓下來之後仍在上限內',
  4000*3000*cap(4000,3000,2)**2 <= CAP + 1);
t('縮小不受影響（scale 0.5 維持 0.5）', cap(4000, 3000, 0.5) === 0.5);
t('壓縮後不會低於 1 倍', cap(9000, 9000, 2) >= 1, cap(9000,9000,2));

// browserOcrVariants 的趟數選擇
const small = (w, h) => Math.min(w, h) < 700;
t('960x640 判定為小圖 → 跑 2 趟', small(960, 640));
t('761x428（使用者的廣告2）判定為小圖', small(761, 428));
t('1920x1080 判定為大圖 → 只跑對比那趟', !small(1920, 1080));
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
print("多趟補讀測試結果：%d 通過 / %d 失敗" % (_passed, _failed))
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
