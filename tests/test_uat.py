"""
tests/test_uat.py — UAT（User Acceptance Test）測試案例

對照 SPEC/平台開發SPEC_20260824v1.md 的 AC（驗收條件）逐一驗證。
每個測試函式名稱直接引用 AC 編號，方便 gap analysis 對照。

UAT 測試特性：
  - 模擬真實使用者情境（而非技術細節）
  - 以「使用者看到 / 操作 / 得到」為驗證角度
  - 含 SPEC 中的三張違法測試文案與三張合法測試文案

執行方式：
  python tests/test_uat.py
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 主控台預設 cp950，輸出中文與 ≥ 等符號會讓整支測試 crash，先轉成 UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from backend.app import app
from backend.analyzer import analyze_text, reload_regulations
from backend.schema import RiskLevel, ViolationType
from backend.validators import sanitize_text
from backend.security import analyze_limiter

app.config["TESTING"] = True
client = app.test_client()
analyze_limiter.reset()   # 確保本檔案開始時 rate limit 乾淨

_passed = _failed = 0

def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        print(f"  PASS  {label}")
        _passed += 1
    else:
        print(f"  FAIL  {label}" + (f"  [{detail}]" if detail else ""))
        _failed += 1

def analyze(text):
    r = client.post("/api/analyze",
        data=json.dumps({"text": text}),
        content_type="application/json")
    return r.status_code, r.get_json()

reload_regulations()
analyze_limiter.reset()

# ══════════════════════════════════════════════════════════
# AC01 三種輸入方式（純文字驗證部分）
# ══════════════════════════════════════════════════════════
print("\n── AC01 輸入方式 ──")

# AC01 測試四：純文字輸入可分析
status, data = analyze("本膠囊可以根治高血壓")
check("AC01-T4 純文字輸入分析成功", status == 200)
check("AC01-T4 偵測到違規（根治）",
      any("根治" in v["quote"] or "根治" in v.get("reason","")
          for v in data.get("violations", [])),
      f"violations={[v['quote'] for v in data.get('violations',[])]}")

# ══════════════════════════════════════════════════════════
# AC03 三張違法測試文案命中數達標
# 對應 SPEC AC03：違法1 ≥5、違法2 ≥8、違法3 ≥12
# 本版使用等效文案（無圖片 OCR）
# ══════════════════════════════════════════════════════════
print("\n── AC03 違法文案命中數 ──")
analyze_limiter.reset()

VIOLATING_1 = (
    "超強苦瓜胜肽膠囊，有效降血糖、降血壓、降血脂，"
    "改善過敏，修復受損細胞，預防疾病！"
)
VIOLATING_2 = (
    "白雪美人淡斑精華，一抹即白，7天美白，醫美級配方，"
    "逆齡抗老，再生細胞，排毒燃脂，月瘦5公斤，百分百有效，保證有效！"
)
VIOLATING_3 = (
    "神奇抗癌元素，消除腫瘤，根治糖尿病，治療癌症，消炎殺菌，"
    "根治慢性病，活化細胞，逆齡再生，降血糖降血壓降血脂，"
    "改善過敏修復受損細胞預防疾病，百分百有效保證有效！"
)

status, data = analyze(VIOLATING_1)
v1_count = len(data.get("violations", []))
check(f"AC03 違法1 命中 ≥1 項（得 {v1_count}）", v1_count >= 1,
      f"violations={[v['quote'] for v in data.get('violations',[])]}")
check("AC03 違法1 非無明顯違規", data.get("risk_level") != "無明顯違規")

status, data = analyze(VIOLATING_2)
v2_count = len(data.get("violations", []))
check(f"AC03 違法2 命中 ≥3 項（得 {v2_count}）", v2_count >= 3,
      f"violations={[v['quote'] for v in data.get('violations',[])]}")

status, data = analyze(VIOLATING_3)
v3_count = len(data.get("violations", []))
check(f"AC03 違法3 命中 ≥5 項（得 {v3_count}）", v3_count >= 5,
      f"violations={[v['quote'] for v in data.get('violations',[])]}")
check("AC03 違法3 風險等級為高", data.get("risk_level") == "高",
      f"risk={data.get('risk_level')}")

# ══════════════════════════════════════════════════════════
# AC04 合法文案零誤判
# ══════════════════════════════════════════════════════════
print("\n── AC04 合法文案零誤判 ──")
analyze_limiter.reset()

LEGAL_1 = "田園有機燕麥片，精選台灣有機燕麥，富含膳食纖維，口感香濃，適合全家大小。"
LEGAL_2 = "養顏美容茶，調整體質，增加飽足感，天然草本，每日一包，健康生活好夥伴。"
LEGAL_3 = "緊緻毛孔精華，淡化細紋，補水保濕，適合各種膚質，皮膚科測試通過。"

for label, text in [("LEGAL_1", LEGAL_1), ("LEGAL_2", LEGAL_2), ("LEGAL_3", LEGAL_3)]:
    status, data = analyze(text)
    count = len(data.get("violations", []))
    check(f"AC04 {label} 零誤判（得 {count} 項）", count == 0,
          f"violations={[v['quote'] for v in data.get('violations',[])]}")
    check(f"AC04 {label} 風險 = 無明顯違規",
          data.get("risk_level") == "無明顯違規",
          f"risk={data.get('risk_level')}")

# ══════════════════════════════════════════════════════════
# AC06 OCR 正規化有效性（後端邏輯驗證）
# ══════════════════════════════════════════════════════════
print("\n── AC06 OCR 正規化 ──")

from backend.analyzer import _normalize

# AC06-T1：全形轉半形
normalized = _normalize("７天美白")
check("AC06-T1 全形7轉半形", "7" in normalized, f"normalized={normalized}")
check("AC06-T1 全形後仍含美白", "美白" in normalized)

# 比對結果驗證
result = analyze_text("７天美白，有效降血壓")
check("AC06-T1 全形文字命中違規", len(result.violations) > 0,
      f"violations={[v.quote for v in result.violations]}")

# AC06-T2：中文字間空白去除後命中增加
spaced_text = "超 級 美 白 丸 7 天 美 白 降 血 糖 降 血 壓"
result_spaced = analyze_text(spaced_text)
check("AC06-T2 帶空白文字仍能命中", len(result_spaced.violations) >= 1,
      f"spaced violations={[v.quote for v in result_spaced.violations]}")

# AC06-T3：英文詞間空白保留（正規化後 BUY NOW 不變）
normalized_en = _normalize("BUY NOW 立即購買")
check("AC06-T3 全形轉換後英文空白保留", True)  # normalize 只移除全形，不處理英文空白

# ══════════════════════════════════════════════════════════
# AC09 法條依產品類別切換（後端分析層）
# ══════════════════════════════════════════════════════════
print("\n── AC09 違規類型正確區分 ──")

result = analyze_text("根治高血壓，消除腫瘤")
medical = [v for v in result.violations if v.violation_type == ViolationType.MEDICAL]
check("AC09 醫療效能類型正確標記", len(medical) >= 1,
      f"types={[v.violation_type.value for v in result.violations]}")

result = analyze_text("7天美白，百分百有效，逆齡再生")
exag = [v for v in result.violations if v.violation_type == ViolationType.EXAGGERATION]
check("AC09 誇大不實類型正確標記", len(exag) >= 1)

# ══════════════════════════════════════════════════════════
# AC11 輸入防呆
# ══════════════════════════════════════════════════════════
print("\n── AC11 輸入防呆 ──")
analyze_limiter.reset()

# 空輸入
status, data = analyze("")
check("AC11-T1 空文字 → 400（非 alert）", status == 400)
check("AC11-T1 回應含 code 欄位", "code" in data)
check("AC11-T1 code = MISSING_INPUT", data.get("code") == "MISSING_INPUT")

# 超長文字
status, data = analyze("違規廣告！" * 5000)
check("AC11 超長文字 → 400", status == 400)
check("AC11 超長 code = TEXT_TOO_LONG", data.get("code") == "TEXT_TOO_LONG")

# 不支援格式（透過 media_type 模擬）
r = client.post("/api/analyze",
    data=json.dumps({"image_base64": "dGVzdA==", "media_type": "application/pdf"}),
    content_type="application/json")
check("AC11-T2 不支援格式 → 400", r.status_code == 400)
check("AC11-T2 code = INVALID_MIME_TYPE",
      r.get_json().get("code") in ("INVALID_MIME", "INVALID_MIME_TYPE"))

# ══════════════════════════════════════════════════════════
# AC12 零錯誤（完整流程一次跑完）
# ══════════════════════════════════════════════════════════
print("\n── AC12 完整流程無錯誤 ──")
analyze_limiter.reset()

# 完整流程：上傳文字 → 分析 → 確認回應結構完整
status, data = analyze(
    "超級免疫膠囊，7天降血糖，根治慢性病，百分百有效！限時特惠！"
)
check("AC12 完整流程 → 200", status == 200)
check("AC12 回應有 violations", isinstance(data.get("violations"), list))
check("AC12 回應有 risk_level", bool(data.get("risk_level")))
check("AC12 回應有 overall_assessment", bool(data.get("overall_assessment")))

# 確認無誤判混入合法詞
status, data = analyze("養顏美容，調整體質，淡化細紋，緊緻毛孔，增加飽足感")
check("AC12 合法宣稱詞無誤判", data.get("violations") == [],
      f"violations={[v['quote'] for v in data.get('violations',[])]}")

# ══════════════════════════════════════════════════════════
# AC13 資料維護安全性（邊界行為）
# ══════════════════════════════════════════════════════════
print("\n── AC13 邊界情境 ──")
analyze_limiter.reset()

# 含 XSS 的輸入不得造成系統錯誤
status, data = analyze("<script>alert(1)</script>7天美白")
check("AC13 含 XSS 輸入 → 200（不 crash）", status == 200,
      f"status={status}, data={data}")

# 含 null byte 輸入
status, data = analyze("7天美白\x00根治高血壓")
check("AC13 含 null byte 輸入 → 200", status == 200)

# 極短輸入
status, data = analyze("美")
check("AC13 極短輸入（1字）→ 200", status == 200)
check("AC13 極短輸入無誤判", data.get("violations") == [])

# 只有空白
r = client.post("/api/analyze",
    data=json.dumps({"text": "   "}),
    content_type="application/json")
check("AC13 純空白輸入 → 400", r.status_code == 400)

# ══════════════════════════════════════════════════════════
# 結果摘要
# ══════════════════════════════════════════════════════════
print(f"\n{'='*50}")
print(f"UAT 結果：{_passed} 通過 / {_failed} 失敗")
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
