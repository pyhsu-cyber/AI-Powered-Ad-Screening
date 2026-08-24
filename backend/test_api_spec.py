"""驗證 api_spec.py 的 JSON Schema 與範例資料一致"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import jsonschema
from backend.api_spec import (
    ANALYZE_REQUEST_SCHEMA, ANALYZE_RESPONSE_SCHEMA,
    STATUS_RESPONSE_SCHEMA, ERROR_RESPONSE_SCHEMA,
    EXAMPLE_ANALYZE_REQUEST, EXAMPLE_ANALYZE_RESPONSE,
    EXAMPLE_STATUS_RESPONSE, EXAMPLE_ERROR_400, EXAMPLE_ERROR_401,
    ERROR_CODE_TABLE, ENDPOINTS, HTTP_STATUS
)
from backend.fixtures import (
    FIXTURE_HIGH_RISK, FIXTURE_MEDIUM_RISK, FIXTURE_NO_VIOLATION
)

passed = 0

def check(label, schema, data):
    global passed
    try:
        jsonschema.validate(instance=data, schema=schema)
        print(f"  PASS  {label}")
        passed += 1
    except jsonschema.ValidationError as e:
        print(f"  FAIL  {label}: {e.message}")

# 1. 範例請求符合 schema（只驗證 text 欄位，image 部分為 null）
req = {k: v for k, v in EXAMPLE_ANALYZE_REQUEST.items() if v is not None}
req.setdefault("text", EXAMPLE_ANALYZE_REQUEST["text"])
check("範例 AnalyzeRequest (text only)", ANALYZE_REQUEST_SCHEMA, req)

# 2. 範例回應符合 schema
check("範例 AnalyzeResponse", ANALYZE_RESPONSE_SCHEMA, EXAMPLE_ANALYZE_RESPONSE)

# 3. 狀態回應符合 schema
check("範例 StatusResponse", STATUS_RESPONSE_SCHEMA, EXAMPLE_STATUS_RESPONSE)

# 4. 錯誤回應符合 schema
check("範例 ErrorResponse 400", ERROR_RESPONSE_SCHEMA, EXAMPLE_ERROR_400)
check("範例 ErrorResponse 401", ERROR_RESPONSE_SCHEMA, EXAMPLE_ERROR_401)

# 5. fixture 回應可轉成 dict 並符合 schema
for name, fix in [("HIGH_RISK", FIXTURE_HIGH_RISK),
                  ("MEDIUM_RISK", FIXTURE_MEDIUM_RISK),
                  ("NO_VIOLATION", FIXTURE_NO_VIOLATION)]:
    check(f"Fixture {name} AnalyzeResponse", ANALYZE_RESPONSE_SCHEMA, fix["response"].to_dict())

# 6. 結構完整性：所有 error code 都有 http_status
for code, meta in ERROR_CODE_TABLE.items():
    assert "http_status" in meta, f"{code} 缺少 http_status"
    assert meta["http_status"] in HTTP_STATUS, f"{code} 的 http_status {meta['http_status']} 不在 HTTP_STATUS 表中"
print(f"  PASS  所有 {len(ERROR_CODE_TABLE)} 個錯誤碼結構完整")
passed += 1

# 7. Endpoint 定義完整性
for name, ep in ENDPOINTS.items():
    assert "path" in ep and "method" in ep, f"Endpoint {name} 缺少 path 或 method"
print(f"  PASS  所有 {len(ENDPOINTS)} 個 Endpoint 結構完整")
passed += 1

print(f"\nOK: {passed}/9 項驗證通過")
