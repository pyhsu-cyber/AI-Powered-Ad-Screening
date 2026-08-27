"""app.py + analyzer.py 冒煙測試（不啟動真實伺服器）"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 主控台預設 cp950，輸出中文與 ≥ 等符號會讓整支測試 crash，先轉成 UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from backend.app import app
from backend.analyzer import analyze_text, reload_regulations
from backend.fixtures import FIXTURE_HIGH_RISK, FIXTURE_MEDIUM_RISK, FIXTURE_NO_VIOLATION

app.config["TESTING"] = True
client = app.test_client()

passed = 0
failed = 0

def check(label, cond, info=""):
    global passed, failed
    if cond:
        print(f"  PASS  {label}")
        passed += 1
    else:
        print(f"  FAIL  {label}" + (f": {info}" if info else ""))
        failed += 1

# ── 1. GET /api/status ────────────────────────────────────
r = client.get("/api/status")
check("GET /api/status 回傳 200", r.status_code == 200)
data = r.get_json()
check("status 含 ai_enabled", "ai_enabled" in data)
check("status 含 mode", "mode" in data)
check("status 含 version", "version" in data)

# ── 2. POST /api/analyze — 缺少輸入 ──────────────────────
r = client.post("/api/analyze",
    json={},
    content_type="application/json")
check("analyze 空請求回傳 400", r.status_code == 400, r.get_data(as_text=True)[:100])
data = r.get_json()
check("400 含 code 欄位", "code" in data)
check("400 code = MISSING_INPUT", data.get("code") == "MISSING_INPUT")

# ── 3. POST /api/analyze — 文字分析（高風險）────────────
text_high = FIXTURE_HIGH_RISK["request"].text
r = client.post("/api/analyze",
    json={"text": text_high},
    content_type="application/json")
check("analyze 高風險文字回傳 200", r.status_code == 200, r.get_data(as_text=True)[:200])
data = r.get_json()
check("回應含 violations", "violations" in data)
check("高風險至少 1 項違規", len(data.get("violations", [])) >= 1,
      f"violations count={len(data.get('violations', []))}")
check("回應含 risk_level", "risk_level" in data)
check("高風險等級為高或中", data.get("risk_level") in ("高", "中"),
      f"risk_level={data.get('risk_level')}")

# ── 4. POST /api/analyze — 無違規文字 ────────────────────
text_ok = FIXTURE_NO_VIOLATION["request"].text
r = client.post("/api/analyze",
    json={"text": text_ok},
    content_type="application/json")
check("analyze 無違規文字回傳 200", r.status_code == 200)
data = r.get_json()
check("無違規 violations 為空", data.get("violations") == [],
      f"violations={data.get('violations')}")
check("無違規 risk_level = 無明顯違規", data.get("risk_level") == "無明顯違規",
      f"risk_level={data.get('risk_level')}")

# ── 5. POST /api/analyze — 無效 JSON ─────────────────────
r = client.post("/api/analyze",
    data="not json",
    content_type="application/json")
check("無效 JSON 回傳 400", r.status_code == 400)

# ── 6. analyzer 直接測試 ──────────────────────────────────
reload_regulations()
result = analyze_text("本產品7天美白，有效降血糖，根治過敏，百分百有效")
check("analyzer 直接呼叫成功", result is not None)
check("analyzer 偵測到違規", len(result.violations) > 0,
      f"violations count={len(result.violations)}")
check("analyzer risk_level 正確", result.risk_level.value in ("高", "中"),
      f"risk_level={result.risk_level}")

# ── 7. 靜態頁面 ───────────────────────────────────────────
r = client.get("/")
check("GET / 回傳 200", r.status_code == 200)

print(f"\n{'OK' if not failed else 'FAIL'}: {passed} 項測試通過"
      + (f"、{failed} 項失敗" if failed else "、全數通過"))
# 直接執行時用結束碼回報失敗。pytest 下不能 exit —— 那會變成 collection
# error 而不是一筆乾淨的測試失敗，下面的 test_all_checks_passed 會接手。
if failed and "pytest" not in sys.modules:
    sys.exit(1)


# ══════════════════════════════════════════════════════════
# pytest 進入點
# ══════════════════════════════════════════════════════════
# 這支檔案的測試邏輯寫在模組層，可以直接 `python <本檔>` 執行。
# 但 pytest 只 import 模組、不會把模組層的斷言當成 test item ——
# 補上這個函式之前，`python -m pytest backend tests` 回報的是
# "no tests ran"（exit 5），等於 README 記載的驗證指令什麼都沒驗。
def test_all_checks_passed():
    """模組層的檢查在 import 時已跑完，這裡把失敗數斷言出來。"""
    assert failed == 0, f"{failed} 項檢查失敗（詳見上方 FAIL 行）"
