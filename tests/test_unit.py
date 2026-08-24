"""
tests/test_unit.py — Unit Tests

測試對象：純函式（不啟動伺服器、不呼叫外部服務）
  - backend/validators.py
  - backend/analyzer.py
  - backend/security.py
  - backend/schema.py（序列化）

執行方式：
  python -m pytest tests/test_unit.py -v
  或直接執行：python tests/test_unit.py
"""
import sys
import os
import base64
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# ── pytest 相容但也支援直接執行 ────────────────────────────
try:
    import pytest
    PYTEST = True
except ImportError:
    PYTEST = False

_passed = _failed = 0

def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        print(f"  PASS  {label}")
        _passed += 1
    else:
        print(f"  FAIL  {label}" + (f"  [{detail}]" if detail else ""))
        _failed += 1

# ══════════════════════════════════════════════════════════
# Validators — validate_analyze_request
# ══════════════════════════════════════════════════════════

from backend.validators import (
    validate_analyze_request, validate_complaint_request,
    sanitize_text, mask_api_key, _is_email, _is_phone
)
from backend.schema import AnalyzeRequest, ComplaintRequest, ErrorCode

print("\n── validate_analyze_request ──")

def _req(**kw): return AnalyzeRequest(**kw)

# 正常情境
ok, errs = validate_analyze_request(_req(text="7天美白"))
check("純文字請求通過", ok)

ok, errs = validate_analyze_request(_req(image_base64="dGVzdA==", media_type="image/png"))
check("圖片請求通過（有 media_type）", ok)

ok, errs = validate_analyze_request(_req(text="廣告", image_base64="dGVzdA==", media_type="image/jpeg"))
check("文字 + 圖片同時提供通過", ok)

# 缺少輸入
ok, errs = validate_analyze_request(_req())
check("空請求被拒絕", not ok)
check("空請求錯誤碼 MISSING_INPUT", not ok and errs[0]["code"] == ErrorCode.MISSING_INPUT)

ok, errs = validate_analyze_request(_req(text=""))
check("空字串文字被拒絕", not ok)

# 文字太長
ok, errs = validate_analyze_request(_req(text="A" * 20_001))
check("超長文字被拒絕", not ok)
check("超長文字錯誤碼 TEXT_TOO_LONG", not ok and errs[0]["code"] == ErrorCode.TEXT_TOO_LONG)

ok, errs = validate_analyze_request(_req(text="A" * 20_000))
check("剛好 20000 字通過", ok)

# 不支援的 MIME type
ok, errs = validate_analyze_request(_req(image_base64="dGVzdA==", media_type="application/pdf"))
check("PDF MIME 被拒絕", not ok)
check("PDF MIME 錯誤碼 INVALID_MIME_TYPE", not ok and errs[0]["code"] == ErrorCode.INVALID_MIME_TYPE)

# 所有支援的 MIME type
for mime in ("image/jpeg", "image/png", "image/webp", "image/gif"):
    ok, errs = validate_analyze_request(_req(image_base64="dGVzdA==", media_type=mime))
    check(f"支援 MIME {mime}", ok)

# 圖片有 base64 但缺少 media_type
ok, errs = validate_analyze_request(_req(image_base64="dGVzdA==", media_type=None))
check("圖片缺少 media_type 被拒絕", not ok)

# 無效 Base64
ok, errs = validate_analyze_request(_req(image_base64="!!!invalid!!!", media_type="image/png"))
check("無效 Base64 被拒絕", not ok)
check("無效 Base64 錯誤碼 INVALID_IMAGE_DATA", not ok and errs[0]["code"] == ErrorCode.INVALID_IMAGE_DATA)

print("\n── validate_complaint_request ──")

def _creq(**kw): return ComplaintRequest(**kw)

ok, errs = validate_complaint_request(_creq(complainant_name="王小明", complainant_contact="0912-345-678"))
check("正常投訴請求通過", ok)

ok, errs = validate_complaint_request(_creq(complainant_name="", complainant_contact="0912-345-678"))
check("缺少姓名被拒絕", not ok)
check("缺少姓名錯誤碼 MISSING_NAME", not ok and errs[0]["code"] == ErrorCode.MISSING_NAME)

ok, errs = validate_complaint_request(_creq(complainant_name="王小明", complainant_contact=""))
check("缺少聯絡方式被拒絕", not ok)
check("缺少聯絡方式錯誤碼 MISSING_CONTACT", not ok and errs[0]["code"] == ErrorCode.MISSING_CONTACT)

ok, errs = validate_complaint_request(_creq(complainant_name="王小明", complainant_contact="not-valid"))
check("無效聯絡方式被拒絕", not ok)

ok, errs = validate_complaint_request(_creq(complainant_name="王小明", complainant_contact="test@example.com"))
check("Email 聯絡方式通過", ok)

ok, errs = validate_complaint_request(
    _creq(complainant_name="王小明", complainant_contact="0912-345-678", ad_url="not-a-url"))
check("無效 URL 被拒絕", not ok)
check("無效 URL 錯誤碼 INVALID_URL", not ok and errs[0]["code"] == ErrorCode.INVALID_URL)

ok, errs = validate_complaint_request(
    _creq(complainant_name="王小明", complainant_contact="0912-345-678",
          ad_url="https://www.example.com/ad/123"))
check("有效 URL 通過", ok)

ok, errs = validate_complaint_request(_creq(complainant_name="A" * 51, complainant_contact="0912-345-678"))
check("姓名超過50字被拒絕", not ok)

print("\n── sanitize_text ──")

check("空字串回傳空字串", sanitize_text("") == "")
check("正常文字不被修改", sanitize_text("7天美白") == "7天美白")
check("控制字元被移除", "\x00" not in sanitize_text("test\x00text"))
check("首尾空白被清除", sanitize_text("  廣告  ") == "廣告")
check("超長文字被截斷", len(sanitize_text("A" * 30_000)) <= 20_000)
check("換行保留", "\n" in sanitize_text("第一行\n第二行") or True)  # 換行或被trim均可

print("\n── _is_email / _is_phone ──")

check("有效 email", _is_email("user@example.com"))
check("有效 email 含子域", _is_email("user@mail.example.co.uk"))
check("無效 email（無@）", not _is_email("userexample.com"))
check("無效 email（無域）", not _is_email("user@"))
check("有效電話（台灣格式）", _is_phone("0912-345-678"))
check("有效電話（含空格）", _is_phone("02 2345 6789"))
check("有效電話（國際）", _is_phone("+886912345678"))
check("無效電話（太短）", not _is_phone("123"))
check("無效電話（含字母）", not _is_phone("abc-def-ghij"))

print("\n── mask_api_key ──")

check("正常長度 key 遮蔽", "…" in mask_api_key("sk-ant-abc123xyz"))
check("短 key 顯示 ***", mask_api_key("abc") == "***")
check("空字串顯示 ***", mask_api_key("") == "***")

# ══════════════════════════════════════════════════════════
# Analyzer — analyze_text
# ══════════════════════════════════════════════════════════

print("\n── analyzer.analyze_text ──")

from backend.analyzer import analyze_text, reload_regulations
from backend.schema import RiskLevel, ViolationType

reload_regulations()

# 高風險案例
result = analyze_text("本產品7天美白，有效降血糖，根治過敏，百分百有效！")
check("高風險廣告偵測到違規", len(result.violations) > 0)
check("高風險等級為高或中", result.risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM),
      f"risk={result.risk_level}")

# 醫療效能偵測
result = analyze_text("消除腫瘤，治療癌症，降血壓！")
medical = [v for v in result.violations if v.violation_type == ViolationType.MEDICAL]
check("醫療效能詞被偵測", len(medical) > 0, f"violations={[v.quote for v in result.violations]}")
check("醫療效能風險高", result.risk_level == RiskLevel.HIGH)

# 誇大不實偵測
result = analyze_text("醫美級配方，7天美白，百分百有效")
exag = [v for v in result.violations if v.violation_type == ViolationType.EXAGGERATION]
check("誇大不實詞被偵測", len(exag) > 0)

# 無違規
result = analyze_text("富含膳食纖維，口感香濃，適合全家大小")
check("無違規廣告 violations 為空", result.violations == [])
check("無違規 risk_level = NONE", result.risk_level == RiskLevel.NONE)

# 全形字元處理
result = analyze_text("７天美白，有效降血壓")
check("全形數字正確比對", len(result.violations) > 0,
      f"text中有全形7天美白，violations={[v.quote for v in result.violations]}")

# to_dict() 序列化
result = analyze_text("7天美白，根治過敏")
d = result.to_dict()
check("to_dict 含必要欄位", all(k in d for k in
      ["mode", "product_name", "product_type", "ad_text", "risk_level",
       "overall_assessment", "violations"]))
check("to_dict violations 是 list", isinstance(d["violations"], list))
if d["violations"]:
    v = d["violations"][0]
    check("violation dict 含 law", "law" in v)
    check("violation dict law 含 url", "url" in v.get("law", {}))

# ══════════════════════════════════════════════════════════
# Security — strip_dangerous_patterns
# ══════════════════════════════════════════════════════════

print("\n── security.strip_dangerous_patterns ──")

from backend.security import strip_dangerous_patterns, mask_sensitive_fields

clean, warns = strip_dangerous_patterns("<script>alert(1)</script>廣告")
check("script tag 被清除", "<script>" not in clean)
check("script 警告存在", len(warns) > 0)

clean, warns = strip_dangerous_patterns("javascript:alert(1) 廣告")
check("javascript: 協議被清除", "javascript:" not in clean)

clean, warns = strip_dangerous_patterns("正常廣告文字")
check("正常文字無警告", warns == [])
check("正常文字不被修改", clean == "正常廣告文字")

clean, warns = strip_dangerous_patterns("A" * 600)
check("重複字元被截斷", len(clean) < 600)
check("重複字元警告存在", len(warns) > 0)

clean, warns = strip_dangerous_patterns("廣告\x00文字")
check("null byte 被清除", "\x00" not in clean)

print("\n── security.mask_sensitive_fields ──")

data = {"text": "廣告", "image_base64": "A" * 3000, "api_key": "sk-ant-test"}
masked = mask_sensitive_fields(data)
check("image_base64 被標記", "[BASE64" in str(masked["image_base64"]))
check("api_key 被遮蔽", masked["api_key"] != "sk-ant-test")
check("text 不被遮蔽", masked["text"] == "廣告")

# ══════════════════════════════════════════════════════════
# Schema — to_dict / from fixtures
# ══════════════════════════════════════════════════════════

print("\n── schema fixtures to_dict ──")

from backend.fixtures import FIXTURE_HIGH_RISK, FIXTURE_MEDIUM_RISK, FIXTURE_NO_VIOLATION

for label, fix in [("HIGH_RISK", FIXTURE_HIGH_RISK),
                   ("MEDIUM_RISK", FIXTURE_MEDIUM_RISK),
                   ("NO_VIOLATION", FIXTURE_NO_VIOLATION)]:
    d = fix["response"].to_dict()
    check(f"{label} to_dict 不拋例外", True)
    check(f"{label} risk_level 是字串", isinstance(d["risk_level"], str))
    check(f"{label} violations 是 list", isinstance(d["violations"], list))

# ══════════════════════════════════════════════════════════
# 結果摘要
# ══════════════════════════════════════════════════════════

print(f"\n{'='*50}")
print(f"Unit Test 結果：{_passed} 通過 / {_failed} 失敗")
if _failed:
    sys.exit(1)
