"""
tests/test_e2e.py — E2E Tests（端對端）

透過 Flask test client 模擬完整請求流程，
驗證從 HTTP 請求進來到 JSON 回應出去的整條路徑。

涵蓋：
  - 正常流程（高風險 / 中風險 / 無違規）
  - 所有 4xx 錯誤情境
  - 安全機制（速率限制、安全 header、API Key）
  - 回應 schema 符合 api_spec.py 定義

執行方式：
  python tests/test_e2e.py
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 主控台預設 cp950，輸出中文與 ≥ 等符號會讓整支測試 crash，先轉成 UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import jsonschema
from backend.app import app
from backend.api_spec import (
    ANALYZE_RESPONSE_SCHEMA, STATUS_RESPONSE_SCHEMA, ERROR_RESPONSE_SCHEMA
)
from backend.fixtures import FIXTURE_HIGH_RISK, FIXTURE_MEDIUM_RISK, FIXTURE_NO_VIOLATION
from backend.schema import ErrorCode
from backend.security import analyze_limiter

app.config["TESTING"] = True
client = app.test_client()
analyze_limiter.reset()  # 確保測試開始時 rate limit 乾淨

_passed = _failed = 0

def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        print(f"  PASS  {label}")
        _passed += 1
    else:
        print(f"  FAIL  {label}" + (f"  [{detail}]" if detail else ""))
        _failed += 1

def post_analyze(payload):
    return client.post("/api/analyze",
        data=json.dumps(payload),
        content_type="application/json")

def validate_schema(data, schema, label):
    try:
        jsonschema.validate(instance=data, schema=schema)
        return True
    except jsonschema.ValidationError as e:
        print(f"          schema 錯誤 ({label}): {e.message[:80]}")
        return False

# ══════════════════════════════════════════════════════════
# 1. GET /api/status
# ══════════════════════════════════════════════════════════
print("\n── GET /api/status ──")

r = client.get("/api/status")
check("回傳 200", r.status_code == 200)
data = r.get_json()
check("回應符合 StatusResponse schema",
      validate_schema(data, STATUS_RESPONSE_SCHEMA, "status"))
check("ai_enabled 為 False（無 ANTHROPIC_API_KEY）", data.get("ai_enabled") is False)
check("mode 為 free", data.get("mode") == "free")
check("version 不為空", bool(data.get("version")))

# ══════════════════════════════════════════════════════════
# 2. POST /api/analyze — 正常流程
# ══════════════════════════════════════════════════════════
print("\n── POST /api/analyze — 正常流程 ──")

# 高風險
r = post_analyze({"text": FIXTURE_HIGH_RISK["request"].text})
check("高風險 → 200", r.status_code == 200)
data = r.get_json()
check("高風險回應符合 schema",
      validate_schema(data, ANALYZE_RESPONSE_SCHEMA, "high_risk"))
check("高風險 violations ≥ 1", len(data.get("violations", [])) >= 1)
check("高風險 risk_level 在高/中", data.get("risk_level") in ("高", "中"),
      f"risk={data.get('risk_level')}")
check("高風險 mode = free", data.get("mode") == "free")
check("高風險 ad_text 不為空", bool(data.get("ad_text")))

# 中風險
r = post_analyze({"text": FIXTURE_MEDIUM_RISK["request"].text})
check("中風險 → 200", r.status_code == 200)
data = r.get_json()
check("中風險 violations ≥ 1", len(data.get("violations", [])) >= 1)

# 無違規
r = post_analyze({"text": FIXTURE_NO_VIOLATION["request"].text})
check("無違規 → 200", r.status_code == 200)
data = r.get_json()
check("無違規回應符合 schema",
      validate_schema(data, ANALYZE_RESPONSE_SCHEMA, "no_violation"))
check("無違規 violations 為空陣列", data.get("violations") == [])
check("無違規 risk_level = 無明顯違規", data.get("risk_level") == "無明顯違規")

# 全形文字
r = post_analyze({"text": "本產品７天美白，有效降血壓！"})
check("全形文字 → 200", r.status_code == 200)
data = r.get_json()
check("全形文字命中違規", len(data.get("violations", [])) >= 1,
      f"violations={[v['quote'] for v in data.get('violations', [])]}")

# 超長正常文字（邊界）
long_ok = "富含膳食纖維，口感香濃。" * 500   # ~6000 字
r = post_analyze({"text": long_ok})
check("長文字（6000字）→ 200", r.status_code == 200)

# ══════════════════════════════════════════════════════════
# 3. POST /api/analyze — 4xx 錯誤情境
# ══════════════════════════════════════════════════════════
print("\n── POST /api/analyze — 4xx 錯誤 ──")

# 空請求 body
r = post_analyze({})
check("空 body → 400", r.status_code == 400)
data = r.get_json()
check("空 body 回應符合 ErrorResponse schema",
      validate_schema(data, ERROR_RESPONSE_SCHEMA, "empty_body"))
check("空 body code = MISSING_INPUT", data.get("code") == ErrorCode.MISSING_INPUT)

# 文字為空字串
r = post_analyze({"text": ""})
check("空字串 text → 400", r.status_code == 400)

# 文字超過 20000 字
r = post_analyze({"text": "違規廣告！" * 5000})
check("超長文字 → 400", r.status_code == 400)
data = r.get_json()
check("超長文字 code = TEXT_TOO_LONG", data.get("code") == ErrorCode.TEXT_TOO_LONG)

# 不支援的 MIME type
r = post_analyze({"image_base64": "dGVzdA==", "media_type": "application/pdf"})
check("PDF MIME → 400", r.status_code == 400)
data = r.get_json()
check("PDF MIME code = INVALID_MIME", data.get("code") == ErrorCode.INVALID_MIME)

# 無效 Base64
r = post_analyze({"image_base64": "!!!invalid!!!", "media_type": "image/png"})
check("無效 Base64 → 400", r.status_code == 400)
data = r.get_json()
check("無效 Base64 code = INVALID_IMAGE_DATA",
      data.get("code") == ErrorCode.INVALID_IMAGE_DATA)

# 非 JSON Content-Type（check_content_type decorator 回 415）
analyze_limiter.reset()
r = client.post("/api/analyze",
    data="text=廣告文字",
    content_type="application/x-www-form-urlencoded")
check("非 JSON Content-Type → 4xx", r.status_code in (400, 415),
      f"status={r.status_code}")

# 非 JSON body（格式錯誤，Flask silent=True → MISSING_INPUT 400）
analyze_limiter.reset()
r = client.post("/api/analyze",
    data="not-json-at-all",
    content_type="application/json")
check("無效 JSON body → 400", r.status_code == 400,
      f"status={r.status_code}, body={r.get_data(as_text=True)[:60]}")

# ══════════════════════════════════════════════════════════
# 4. HTTP 方法不允許
# ══════════════════════════════════════════════════════════
print("\n── HTTP 方法 ──")

r = client.get("/api/analyze")
check("GET /api/analyze → 404 或 405", r.status_code in (404, 405))

r = client.delete("/api/analyze")
check("DELETE /api/analyze → 405", r.status_code == 405)

r = client.post("/api/status",
    data=json.dumps({}), content_type="application/json")
check("POST /api/status → 405", r.status_code == 405)

# ══════════════════════════════════════════════════════════
# 5. 安全 Header
# ══════════════════════════════════════════════════════════
print("\n── 安全 Header ──")

r = client.get("/api/status")
check("X-Content-Type-Options: nosniff",
      r.headers.get("X-Content-Type-Options") == "nosniff")
check("X-Frame-Options: DENY",
      r.headers.get("X-Frame-Options") == "DENY")
check("X-XSS-Protection 存在",
      "X-XSS-Protection" in r.headers)

r = post_analyze({"text": "7天美白"})
check("/api/analyze Cache-Control 含 no-store",
      "no-store" in r.headers.get("Cache-Control", ""))
check("/api/analyze X-RateLimit-Limit 存在",
      "X-RateLimit-Limit" in r.headers)
check("/api/analyze X-RateLimit-Remaining 存在",
      "X-RateLimit-Remaining" in r.headers)

# ══════════════════════════════════════════════════════════
# 6. 速率限制
# ══════════════════════════════════════════════════════════
print("\n── 速率限制 ──")

# 重置避免先前測試污染
analyze_limiter.reset()

# 建立一個超過限制的 limiter 做測試
from backend.security import RateLimiter
tiny_limiter = RateLimiter(max_calls=2, window_seconds=60)
tiny_limiter.reset()

ok1, _ = tiny_limiter.is_allowed("e2e-test-ip")
ok2, _ = tiny_limiter.is_allowed("e2e-test-ip")
ok3, _ = tiny_limiter.is_allowed("e2e-test-ip")
check("速率限制：2次後拒絕", ok1 and ok2 and not ok3,
      f"{ok1},{ok2},{ok3}")

# 回應含 Retry-After header（觸發 429 後）
# 直接透過 app endpoint 測試需要大量請求，改用 limiter 邏輯驗證
allowed, remaining = analyze_limiter.is_allowed("127.0.0.1")
check("速率限制：正常請求被允許", allowed)
analyze_limiter.reset()

# ══════════════════════════════════════════════════════════
# 7. 靜態頁面
# ══════════════════════════════════════════════════════════
print("\n── 靜態頁面 ──")

r = client.get("/")
check("GET / → 200", r.status_code == 200)
check("GET / 回傳 HTML", "text/html" in r.content_type)
html = r.get_data(as_text=True)
# 瀏覽器端 E2E 以 id 選取元素，這裡守住 id 契約：
# 任何一個被 build.py 改名，都會在這裡先報出來，而不是讓 puppeteer 莫名其妙掛掉。
_REQUIRED_IDS = ["adText", "analyzeBtn", "resultCard", "vioList",
                 "genBtn", "previewCard", "letterPreview",
                 "fName", "fContact", "fPlatform", "fType",
                 "file", "drop"]
_missing = [i for i in _REQUIRED_IDS if 'id="%s"' % i not in html]
check("頁面含 E2E 依賴的全部元素 id", not _missing, "缺少 " + ", ".join(_missing))

# ══════════════════════════════════════════════════════════
# 8. 回應欄位完整性逐一驗證
# ══════════════════════════════════════════════════════════
print("\n── 回應欄位完整性 ──")

r = post_analyze({"text": "本產品7天美白，有效降血糖，根治過敏！"})
data = r.get_json()
required_fields = ["mode", "product_name", "product_type", "ad_text",
                   "risk_level", "overall_assessment", "violations"]
for f in required_fields:
    check(f"回應含欄位 {f}", f in data)

if data.get("violations"):
    v = data["violations"][0]
    vio_fields = ["quote", "violation_type", "reason", "confidence", "law"]
    for f in vio_fields:
        check(f"violation 含欄位 {f}", f in v)
    law_fields = ["id", "law_name", "article", "summary", "penalty", "url"]
    for f in law_fields:
        check(f"law 含欄位 {f}", f in v.get("law", {}))

# ══════════════════════════════════════════════════════════
# 結果
# ══════════════════════════════════════════════════════════
print(f"\n{'='*50}")
print(f"E2E Test 結果：{_passed} 通過 / {_failed} 失敗")
# 直接執行時用結束碼回報失敗。pytest 下不能 exit —— 那會變成 collection
# error 而不是一筆乾淨的測試失敗，下面的 test_all_checks_passed 會接手。
if _failed and "pytest" not in sys.modules:
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
    assert _failed == 0, f"{_failed} 項檢查失敗（詳見上方 FAIL 行）"
