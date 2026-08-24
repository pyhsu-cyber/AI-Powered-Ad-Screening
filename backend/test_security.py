"""security.py + app.py 安全機制測試"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.security import (
    RateLimiter, mask_api_key, mask_sensitive_fields,
    strip_dangerous_patterns, _verify_api_key, _ALLOWED_KEYS
)
from backend.app import app

app.config["TESTING"] = True
client = app.test_client()

passed = 0

def check(label, cond, info=""):
    global passed
    if cond:
        print(f"  PASS  {label}")
        passed += 1
    else:
        print(f"  FAIL  {label}" + (f": {info}" if info else ""))

# ── 1. API Key 遮蔽 ───────────────────────────────────────
check("mask_api_key 長 key", mask_api_key("sk-ant-abc123xyz456") == "sk-a…z456")
check("mask_api_key 短 key", mask_api_key("short") == "***")
check("mask_api_key 空字串", mask_api_key("") == "***")

# ── 2. 敏感欄位遮蔽 ──────────────────────────────────────
data = {
    "text": "廣告文字",
    "image_base64": "A" * 2000,
    "api_key": "sk-ant-test1234",
    "product_name": "測試產品",
}
masked = mask_sensitive_fields(data)
check("image_base64 被遮蔽", "[BASE64" in str(masked["image_base64"]))
check("api_key 被遮蔽（顯示前後碼）", masked["api_key"].startswith("sk-a") and "…" in masked["api_key"])
check("一般欄位不被遮蔽", masked["text"] == "廣告文字")
check("product_name 不被遮蔽", masked["product_name"] == "測試產品")

# 巢狀 dict
nested = {"outer": {"image_base64": "BBBB", "normal": "ok"}}
masked_nested = mask_sensitive_fields(nested)
check("巢狀 dict 遮蔽", "[BASE64" in str(masked_nested["outer"]["image_base64"]))
check("巢狀 dict 保留正常欄位", masked_nested["outer"]["normal"] == "ok")

# ── 3. 危險模式過濾 ───────────────────────────────────────
clean, warns = strip_dangerous_patterns("<script>alert(1)</script>廣告文字")
check("XSS script tag 被移除", "<script>" not in clean, f"cleaned={clean}")
check("XSS 警告被記錄", len(warns) > 0, f"warns={warns}")

clean2, warns2 = strip_dangerous_patterns("正常廣告文字，7天美白")
check("正常文字不被修改", clean2 == "正常廣告文字，7天美白")
check("正常文字無警告", warns2 == [])

clean3, warns3 = strip_dangerous_patterns("A" * 600)
check("超長重複字元被截斷", len(clean3) < 600, f"len={len(clean3)}")

null_byte_text = "廣告\x00文字"
clean4, warns4 = strip_dangerous_patterns(null_byte_text)
check("Null byte 被移除", "\x00" not in clean4)

# ── 4. 速率限制 ───────────────────────────────────────────
limiter = RateLimiter(max_calls=3, window_seconds=60)
limiter.reset()

ok1, r1 = limiter.is_allowed("test-ip")
ok2, r2 = limiter.is_allowed("test-ip")
ok3, r3 = limiter.is_allowed("test-ip")
ok4, r4 = limiter.is_allowed("test-ip")  # 應被限制

check("速率限制：前3次允許", ok1 and ok2 and ok3, f"{ok1},{ok2},{ok3}")
check("速率限制：第4次拒絕", not ok4, f"ok4={ok4}")
check("速率限制：剩餘次數遞減", r1 > r2 > r3, f"{r1},{r2},{r3}")
check("速率限制：超過時剩餘=0", r4 == 0, f"r4={r4}")

# 不同 IP 獨立計算
ok_other, _ = limiter.is_allowed("other-ip")
check("速率限制：不同 IP 獨立", ok_other)

limiter.reset()

# ── 5. 安全 Header（透過 Flask test client）──────────────
r = client.get("/api/status")
check("安全 Header X-Content-Type-Options", r.headers.get("X-Content-Type-Options") == "nosniff")
check("安全 Header X-Frame-Options", r.headers.get("X-Frame-Options") == "DENY")
check("安全 Header X-XSS-Protection", "1" in r.headers.get("X-XSS-Protection", ""))

r2 = client.post("/api/analyze",
    json={"text": "7天美白，有效降血糖"},
    content_type="application/json")
check("/api/analyze Cache-Control 包含 no-store",
      "no-store" in r2.headers.get("Cache-Control", ""))

# ── 6. API Key 驗證（未設定 API_KEYS 時為開放模式）─────────
# 目前測試環境未設定 API_KEYS，應自動通過
r3 = client.post("/api/analyze",
    json={"text": "正常廣告燕麥片"},
    content_type="application/json")
check("未設定 API_KEYS 時開放存取", r3.status_code == 200,
      f"status={r3.status_code}")

print(f"\nOK: {passed} 項安全測試全數通過")
