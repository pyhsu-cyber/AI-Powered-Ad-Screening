"""
api_spec.py — API 契約定義

本檔定義所有 Endpoint 的規格，包含：
  - 路由、HTTP 方法
  - 請求 / 回應 JSON Schema（dict 格式，可直接餵給 jsonschema.validate）
  - 錯誤碼對照表
  - HTTP 狀態碼語意

實作（app.py）與測試（test_api.py）都應以此為唯一的「真相來源」。
"""

# ═══════════════════════════════════════════════════════════
# Endpoint 清單
# ═══════════════════════════════════════════════════════════

ENDPOINTS = {
    "status": {
        "path": "/api/status",
        "method": "GET",
        "summary": "查詢系統狀態（目前使用的分析模式、版本號）",
        "auth_required": False,
        "rate_limit": "60 req/min",
    },
    "analyze": {
        "path": "/api/analyze",
        "method": "POST",
        "summary": "上傳廣告圖片或文字，執行違規快篩分析",
        "auth_required": False,   # Task #6 安全切片會改為 True（含 API Key）
        "rate_limit": "10 req/min",
        "max_body_bytes": 12 * 1024 * 1024,   # 12 MB（含 Base64 overhead）
    },
}


# ═══════════════════════════════════════════════════════════
# JSON Schema：請求本體
# ═══════════════════════════════════════════════════════════

ANALYZE_REQUEST_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AnalyzeRequest",
    "type": "object",
    "properties": {
        "image_base64": {
            "type": ["string", "null"],
            "description": "圖片的 Base64 編碼（不含 data:image/… 前綴）",
            "maxLength": 14_000_000,   # ~10 MB decoded
        },
        "media_type": {
            "type": ["string", "null"],
            "enum": ["image/jpeg", "image/png", "image/webp", "image/gif", None],
            "description": "圖片 MIME type，提供 image_base64 時必填",
        },
        "text": {
            "type": "string",
            "description": "廣告文字內容（OCR 結果或手動貼入），最多 20,000 字元",
            "maxLength": 20_000,
            "default": "",
        },
        "api_key": {
            "type": ["string", "null"],
            "description": "API Key（Task #6 啟用安全機制後必填）",
        },
    },
    # image_base64 與 text 至少一項不為空的條件在驗證器程式碼中處理，
    # JSON Schema 本身不易表達「互斥必填」，改用 anyOf 近似描述
    "anyOf": [
        {"required": ["image_base64"], "properties": {"image_base64": {"type": "string", "minLength": 1}}},
        {"required": ["text"],         "properties": {"text":         {"type": "string", "minLength": 1}}},
    ],
    "additionalProperties": False,
}


# ═══════════════════════════════════════════════════════════
# JSON Schema：回應本體
# ═══════════════════════════════════════════════════════════

VIOLATION_SCHEMA = {
    "type": "object",
    "required": ["quote", "violation_type", "reason", "law", "confidence"],
    "properties": {
        "quote":          {"type": "string", "description": "廣告原文（逐字引用）"},
        "violation_type": {"type": "string", "enum": ["誇大不實", "宣稱醫療效能"]},
        "reason":         {"type": "string", "description": "違規原因說明"},
        "confidence":     {"type": "string", "enum": ["高", "中", "低"]},
        "law": {
            "type": "object",
            "required": ["id", "law_name", "article", "summary", "penalty", "url"],
            "properties": {
                "id":       {"type": "string"},
                "law_name": {"type": "string"},
                "article":  {"type": "string"},
                "summary":  {"type": "string"},
                "penalty":  {"type": "string"},
                "url":      {"type": "string", "format": "uri"},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}

ANALYZE_RESPONSE_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AnalyzeResponse",
    "type": "object",
    "required": [
        "mode", "product_name", "product_type", "ad_text",
        "risk_level", "overall_assessment", "violations"
    ],
    "properties": {
        "mode": {
            "type": "string",
            "enum": ["free", "gemini", "claude"],
            "description": "實際使用的分析模式",
        },
        "product_name": {
            "type": "string",
            "description": "廣告中辨識到的產品名稱，無法辨識時為「未標示」",
        },
        "product_type": {
            "type": "string",
            "enum": ["食品", "健康食品", "化粧品", "藥品", "醫療器材", "其他", "無法判定"],
        },
        "ad_text": {
            "type": "string",
            "description": "廣告文字（OCR 結果或使用者提供），供前端回填文字框",
        },
        "risk_level": {
            "type": "string",
            "enum": ["高", "中", "低", "無明顯違規"],
        },
        "overall_assessment": {
            "type": "string",
            "description": "整體違規評估說明（2-3 句）",
        },
        "violations": {
            "type": "array",
            "items": VIOLATION_SCHEMA,
            "description": "違規項目清單，無違規時為空陣列",
        },
    },
    "additionalProperties": False,
}

STATUS_RESPONSE_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "StatusResponse",
    "type": "object",
    "required": ["ai_enabled", "mode", "version"],
    "properties": {
        "ai_enabled": {"type": "boolean", "description": "是否啟用 AI 模式（Claude）"},
        "mode":       {"type": "string",  "enum": ["free", "gemini", "claude"]},
        "version":    {"type": "string",  "description": "系統版本號"},
    },
    "additionalProperties": False,
}

ERROR_RESPONSE_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "ErrorResponse",
    "type": "object",
    "required": ["code", "message"],
    "properties": {
        "code":    {"type": "string", "description": "機器可讀的錯誤代碼"},
        "message": {"type": "string", "description": "給使用者看的說明"},
        "detail":  {"type": "string", "description": "開發用詳細資訊（僅 debug 模式回傳）"},
    },
    "additionalProperties": False,
}


# ═══════════════════════════════════════════════════════════
# HTTP 狀態碼對照表
# ═══════════════════════════════════════════════════════════

HTTP_STATUS = {
    # 成功
    200: "OK — 分析完成，回傳 AnalyzeResponse / StatusResponse",
    # 用戶端錯誤
    400: "Bad Request — 輸入驗證失敗（MISSING_INPUT / TEXT_TOO_LONG / INVALID_MIME 等）",
    401: "Unauthorized — 未提供 API Key 或 Key 無效（Task #6 啟用後生效）",
    405: "Method Not Allowed — 使用了不支援的 HTTP 方法",
    413: "Payload Too Large — 請求本體超過 12 MB",
    429: "Too Many Requests — 超過速率限制",
    # 伺服器錯誤
    500: "Internal Server Error — 伺服器內部錯誤（OCR_FAILED / INTERNAL_ERROR）",
    503: "Service Unavailable — AI 服務不可用（AI_UNAVAILABLE）",
}


# ═══════════════════════════════════════════════════════════
# 錯誤碼完整對照表（code → HTTP status, 說明, 使用場景）
# ═══════════════════════════════════════════════════════════

ERROR_CODE_TABLE = {
    # ── 輸入驗證 ──────────────────────────────────────────
    "MISSING_INPUT": {
        "http_status": 400,
        "description": "image_base64 與 text 皆為空",
        "trigger": "AnalyzeRequest 兩個來源欄位都是空值",
        "example_message": "請提供廣告截圖或廣告文字，兩者至少需要一項。",
    },
    "TEXT_TOO_LONG": {
        "http_status": 400,
        "description": "廣告文字超過 20,000 字元",
        "trigger": "len(text) > 20000",
        "example_message": "廣告文字不得超過 20,000 字元。",
    },
    "INVALID_MIME_TYPE": {
        "http_status": 400,
        "description": "不支援的圖片 MIME type",
        "trigger": "media_type 不在 {image/jpeg, image/png, image/webp, image/gif}",
        "example_message": "不支援的圖片格式。支援格式：image/jpeg, image/png, image/webp, image/gif。",
    },
    "IMAGE_TOO_LARGE": {
        "http_status": 400,
        "description": "圖片解碼後超過 10 MB",
        "trigger": "base64 解碼後位元組數 > 10 * 1024 * 1024",
        "example_message": "圖片超過大小上限（10 MB），請壓縮後再試。",
    },
    "INVALID_IMAGE_DATA": {
        "http_status": 400,
        "description": "image_base64 不是有效的 Base64 編碼",
        "trigger": "base64.b64decode() 拋出例外",
        "example_message": "圖片資料格式有誤，請確認 Base64 編碼完整。",
    },
    "INVALID_URL": {
        "http_status": 400,
        "description": "廣告網址格式錯誤",
        "trigger": "ad_url 不符合 https?:// 開頭的 URL 格式",
        "example_message": "廣告網址格式有誤，請以 http:// 或 https:// 開頭。",
    },
    "MISSING_NAME": {
        "http_status": 400,
        "description": "缺少檢舉人姓名",
        "trigger": "complainant_name 為空或超過 50 字",
        "example_message": "請填寫檢舉人姓名。",
    },
    "MISSING_CONTACT": {
        "http_status": 400,
        "description": "缺少或格式錯誤的聯絡方式",
        "trigger": "complainant_contact 為空或不符合電話/Email 格式",
        "example_message": "請填寫有效的電話號碼或 Email。",
    },
    # ── 安全（Task #6 啟用後生效）──────────────────────────
    "MISSING_API_KEY": {
        "http_status": 401,
        "description": "請求未提供 API Key",
        "trigger": "Header X-API-Key 缺失且 body.api_key 也為空",
        "example_message": "請提供 API Key。",
    },
    "INVALID_API_KEY": {
        "http_status": 401,
        "description": "API Key 無效或已失效",
        "trigger": "Key 不在允許清單中",
        "example_message": "API Key 無效，請確認後重試。",
    },
    "RATE_LIMIT_EXCEEDED": {
        "http_status": 429,
        "description": "超過速率限制",
        "trigger": "同一 IP 每分鐘超過 10 次 /api/analyze 請求",
        "example_message": "請求過於頻繁，請稍後再試。",
    },
    # ── 伺服器錯誤 ─────────────────────────────────────────
    "OCR_FAILED": {
        "http_status": 500,
        "description": "OCR 辨識失敗",
        "trigger": "ocr.ps1 執行失敗或 timeout",
        "example_message": "圖片辨識失敗，請確認圖片格式正確，或手動輸入廣告文字。",
    },
    "AI_UNAVAILABLE": {
        "http_status": 503,
        "description": "AI 服務（Claude API）不可用",
        "trigger": "Anthropic API 回傳 5xx 或連線逾時",
        "example_message": "AI 分析服務暫時不可用，請稍後再試，或切換至免費 OCR 模式。",
    },
    "INTERNAL_ERROR": {
        "http_status": 500,
        "description": "伺服器內部未預期錯誤",
        "trigger": "未被捕捉的例外",
        "example_message": "系統發生錯誤，請重試。若問題持續請聯繫管理員。",
    },
}


# ═══════════════════════════════════════════════════════════
# 請求 / 回應範例（供文件與測試使用）
# ═══════════════════════════════════════════════════════════

EXAMPLE_ANALYZE_REQUEST = {
    "text": "本產品 7 天美白，有效降血糖，根治過敏，醫美級配方，百分百有效！",
    "image_base64": None,
    "media_type": None,
}

EXAMPLE_ANALYZE_RESPONSE = {
    "mode": "free",
    "product_name": "超級美白丸",
    "product_type": "食品",
    "ad_text": "本產品 7 天美白，有效降血糖，根治過敏，醫美級配方，百分百有效！",
    "risk_level": "高",
    "overall_assessment": "廣告宣稱降血糖、根治過敏等醫療效能，並使用誇大用語，涉嫌多項違規。",
    "violations": [
        {
            "quote": "有效降血糖",
            "violation_type": "宣稱醫療效能",
            "reason": "降血糖屬醫療效能，食品廣告不得宣稱。",
            "confidence": "高",
            "law": {
                "id": "fsa-28-2",
                "law_name": "食品安全衛生管理法",
                "article": "第28條第2項",
                "summary": "食品不得為醫療效能之標示、宣傳或廣告。",
                "penalty": "依同法第45條第1項，處新臺幣60萬元以上500萬元以下罰鍰。",
                "url": "https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0040001&flno=28",
            },
        },
        {
            "quote": "百分百有效",
            "violation_type": "誇大不實",
            "reason": "絕對性保證用語屬誇大宣傳。",
            "confidence": "高",
            "law": {
                "id": "fsa-28-1",
                "law_name": "食品安全衛生管理法",
                "article": "第28條第1項",
                "summary": "食品廣告不得有不實、誇張或易生誤解之情形。",
                "penalty": "依同法第45條第1項，處新臺幣4萬元以上400萬元以下罰鍰。",
                "url": "https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0040001&flno=28",
            },
        },
    ],
}

EXAMPLE_ERROR_400 = {
    "code": "MISSING_INPUT",
    "message": "請提供廣告截圖或廣告文字，兩者至少需要一項。",
}

EXAMPLE_ERROR_401 = {
    "code": "INVALID_API_KEY",
    "message": "API Key 無效，請確認後重試。",
}

EXAMPLE_ERROR_429 = {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "請求過於頻繁，請稍後再試。",
}

EXAMPLE_STATUS_RESPONSE = {
    "ai_enabled": False,
    "mode": "free",
    "version": "2.0.0",
}
