"""快速冒煙測試，驗證 schema / validators / fixtures 正確載入"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 主控台預設 cp950，輸出中文與 ≥ 等符號會讓整支測試 crash，先轉成 UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from backend.schema import AnalyzeRequest, ErrorCode, ProductType, RiskLevel
from backend.validators import validate_analyze_request, validate_complaint_request, sanitize_text
from backend.fixtures import FIXTURE_HIGH_RISK, FIXTURE_MEDIUM_RISK, FIXTURE_NO_VIOLATION, FIXTURE_EDGE_CASES

# 1. enum 值
assert ProductType.FOOD.value == "食品"
assert RiskLevel.HIGH.value == "高"

# 2. 驗證器：缺少輸入
req = FIXTURE_EDGE_CASES["empty_text"]
ok, errors = validate_analyze_request(req)
assert not ok
assert errors[0]["code"] == "MISSING_INPUT"

# 3. 驗證器：正常請求應通過
ok, errors = validate_analyze_request(FIXTURE_HIGH_RISK["request"])
assert ok, f"應通過但失敗: {errors}"

# 4. 驗證器：缺少姓名
ok, errors = validate_complaint_request(FIXTURE_EDGE_CASES["missing_name"])
assert not ok
assert errors[0]["code"] == "MISSING_NAME"

# 5. to_dict()
d = FIXTURE_HIGH_RISK["response"].to_dict()
assert d["risk_level"] == "高"
assert len(d["violations"]) == 3

# 6. sanitize_text：控制字元被移除，換行與首尾空白處理
cleaned = sanitize_text("  test\x00\x01text\n  ")
assert "\x00" not in cleaned and "\x01" not in cleaned, "控制字元應被移除"
assert cleaned == cleaned.strip(), "首尾空白應被清除"

# 7. 無違規 fixture
assert FIXTURE_NO_VIOLATION["response"].violations == []
assert FIXTURE_NO_VIOLATION["response"].risk_level.value == "無明顯違規"

print("OK: 所有冒煙測試通過 (7/7)")
vio_count = len(FIXTURE_HIGH_RISK["response"].violations)
edge_count = len(FIXTURE_EDGE_CASES)
print(f"  schema: {len(list(ProductType))} 種產品類別, {len(list(RiskLevel))} 種風險等級")
print(f"  fixtures: {vio_count} 項高風險違規, {edge_count} 種邊界情境")
