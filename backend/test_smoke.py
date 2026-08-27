"""快速冒煙測試，驗證 schema / validators / fixtures 正確載入

可以直接 `python backend/test_smoke.py` 執行，也可以被 pytest 收集。
過去這支檔案的斷言全寫在模組層，pytest 只會 import、不會當成 test item，
`python -m pytest backend tests` 因此回報 "no tests ran"。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 主控台預設 cp950，輸出中文與 ≥ 等符號會讓整支測試 crash，先轉成 UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from backend.schema import AnalyzeRequest, ErrorCode, ProductType, RiskLevel
from backend.validators import validate_analyze_request, validate_complaint_request, sanitize_text
from backend.fixtures import FIXTURE_HIGH_RISK, FIXTURE_MEDIUM_RISK, FIXTURE_NO_VIOLATION, FIXTURE_EDGE_CASES


def test_enum_values():
    assert ProductType.FOOD.value == "食品"
    assert RiskLevel.HIGH.value == "高"


def test_validator_rejects_empty_input():
    ok, errors = validate_analyze_request(FIXTURE_EDGE_CASES["empty_text"])
    assert not ok
    assert errors[0]["code"] == "MISSING_INPUT"


def test_validator_accepts_valid_request():
    ok, errors = validate_analyze_request(FIXTURE_HIGH_RISK["request"])
    assert ok, f"應通過但失敗: {errors}"


def test_validator_rejects_missing_name():
    ok, errors = validate_complaint_request(FIXTURE_EDGE_CASES["missing_name"])
    assert not ok
    assert errors[0]["code"] == "MISSING_NAME"


def test_response_to_dict():
    d = FIXTURE_HIGH_RISK["response"].to_dict()
    assert d["risk_level"] == "高"
    assert len(d["violations"]) == 3


def test_sanitize_text_strips_control_chars():
    cleaned = sanitize_text("  test\x00\x01text\n  ")
    assert "\x00" not in cleaned and "\x01" not in cleaned, "控制字元應被移除"
    assert cleaned == cleaned.strip(), "首尾空白應被清除"


def test_no_violation_fixture():
    assert FIXTURE_NO_VIOLATION["response"].violations == []
    assert FIXTURE_NO_VIOLATION["response"].risk_level.value == "無明顯違規"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            failed += 1
    print(f"\n{'OK' if not failed else 'FAIL'}: {len(tests) - failed}/{len(tests)} 項冒煙測試通過")
    print(f"  schema: {len(list(ProductType))} 種產品類別, {len(list(RiskLevel))} 種風險等級")
    print(f"  fixtures: {len(FIXTURE_HIGH_RISK['response'].violations)} 項高風險違規, "
          f"{len(FIXTURE_EDGE_CASES)} 種邊界情境")
    if failed:
        sys.exit(1)
