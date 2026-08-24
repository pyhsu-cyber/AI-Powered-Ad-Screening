"""
validators.py — 輸入驗證規則

每個 validate_* 函式回傳 (ok: bool, errors: list[str])。
errors 為空時代表驗證通過。

設計原則：
  - 純函式，不依賴任何外部服務或狀態
  - 每個規則獨立，可單獨測試
  - 錯誤訊息使用 ErrorCode 常數，方便前端 i18n
"""

from __future__ import annotations

import base64
import re
from typing import Optional, Tuple, List

from .schema import AnalyzeRequest, ComplaintRequest, ErrorCode

# ── 常數 ──────────────────────────────────────────────────

MAX_TEXT_LENGTH    = 20_000        # 字元
MAX_IMAGE_BYTES    = 10 * 1024 * 1024  # 10 MB（解碼後）
ALLOWED_MIME_TYPES = frozenset({
    "image/jpeg", "image/png", "image/webp", "image/gif"
})
URL_PATTERN = re.compile(r'^https?://[^\s/$.?#].[^\s]*$', re.IGNORECASE)
EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
PHONE_PATTERN = re.compile(r'^[\d\s\-\+\(\)]{7,20}$')
MAX_NAME_LENGTH    = 50
MIN_NAME_LENGTH    = 1


# ── AnalyzeRequest 驗證 ───────────────────────────────────

def validate_analyze_request(req: AnalyzeRequest) -> Tuple[bool, List[dict]]:
    """
    驗證 /api/analyze 的請求本體。

    回傳 (ok, errors)，errors 格式：
      [{"code": "...", "field": "...", "message": "..."}]
    """
    errors: List[dict] = []

    # 規則 1：image_base64 與 text 至少一項不為空
    has_image = bool(req.image_base64 and req.image_base64.strip())
    has_text  = bool(req.text and req.text.strip())
    if not has_image and not has_text:
        errors.append({
            "code": ErrorCode.MISSING_INPUT,
            "field": "image_base64 / text",
            "message": "請提供廣告截圖（image_base64）或廣告文字（text），兩者至少需要一項。"
        })
        return False, errors  # 後續規則無法繼續，提前返回

    # 規則 2：text 長度上限
    if has_text and len(req.text) > MAX_TEXT_LENGTH:
        errors.append({
            "code": ErrorCode.TEXT_TOO_LONG,
            "field": "text",
            "message": f"廣告文字不得超過 {MAX_TEXT_LENGTH:,} 字元（目前 {len(req.text):,} 字元）。"
        })

    # 規則 3：有圖片時，media_type 必須存在且在允許清單內
    if has_image:
        if not req.media_type:
            errors.append({
                "code": ErrorCode.INVALID_MIME,
                "field": "media_type",
                "message": "提供圖片時必須同時指定 media_type（例如 image/jpeg）。"
            })
        elif req.media_type.lower() not in ALLOWED_MIME_TYPES:
            errors.append({
                "code": ErrorCode.INVALID_MIME,
                "field": "media_type",
                "message": f"不支援的圖片格式 '{req.media_type}'。支援格式：{', '.join(sorted(ALLOWED_MIME_TYPES))}。"
            })

        # 規則 4：圖片大小上限（解碼後）
        if not errors:  # MIME 驗證通過才繼續
            decoded_size = _base64_decoded_size(req.image_base64)
            if decoded_size is None:
                errors.append({
                    "code": ErrorCode.INVALID_IMAGE_DATA,
                    "field": "image_base64",
                    "message": "image_base64 不是有效的 Base64 編碼，請確認圖片資料完整。"
                })
            elif decoded_size > MAX_IMAGE_BYTES:
                mb = decoded_size / 1024 / 1024
                errors.append({
                    "code": ErrorCode.IMAGE_TOO_LARGE,
                    "field": "image_base64",
                    "message": f"圖片解碼後 {mb:.1f} MB，超過上限 {MAX_IMAGE_BYTES // 1024 // 1024} MB。"
                })

    return len(errors) == 0, errors


# ── ComplaintRequest 驗證 ─────────────────────────────────

def validate_complaint_request(req: ComplaintRequest) -> Tuple[bool, List[dict]]:
    """驗證陳情信生成請求。"""
    errors: List[dict] = []

    # 規則 1：檢舉人姓名必填
    name = (req.complainant_name or "").strip()
    if not name:
        errors.append({
            "code": ErrorCode.MISSING_NAME,
            "field": "complainant_name",
            "message": "請填寫檢舉人姓名。"
        })
    elif len(name) > MAX_NAME_LENGTH:
        errors.append({
            "code": ErrorCode.MISSING_NAME,
            "field": "complainant_name",
            "message": f"姓名不得超過 {MAX_NAME_LENGTH} 字元。"
        })

    # 規則 2：聯絡方式必填，且為電話或 Email 格式
    contact = (req.complainant_contact or "").strip()
    if not contact:
        errors.append({
            "code": ErrorCode.MISSING_CONTACT,
            "field": "complainant_contact",
            "message": "請填寫聯絡方式（電話或 Email）。"
        })
    elif not (_is_email(contact) or _is_phone(contact)):
        errors.append({
            "code": ErrorCode.MISSING_CONTACT,
            "field": "complainant_contact",
            "message": "聯絡方式格式有誤，請填寫有效的電話號碼或 Email。"
        })

    # 規則 3：廣告網址格式（選填）
    url = (req.ad_url or "").strip()
    if url and not URL_PATTERN.match(url):
        errors.append({
            "code": ErrorCode.INVALID_URL,
            "field": "ad_url",
            "message": "廣告網址格式有誤，請填寫完整 URL（以 http:// 或 https:// 開頭）。"
        })

    return len(errors) == 0, errors


# ── 工具函式 ──────────────────────────────────────────────

def _base64_decoded_size(b64: Optional[str]) -> Optional[int]:
    """
    估算 Base64 字串解碼後的位元組數。
    回傳 None 表示 b64 不是有效的 Base64。
    """
    if not b64:
        return None
    try:
        # 先做輕量估算（避免大圖實際解碼）
        stripped = b64.rstrip("=")
        estimated = len(stripped) * 3 // 4

        # 如果估算超過上限就直接拒絕，否則實際解碼驗證格式
        if estimated > MAX_IMAGE_BYTES * 1.05:
            return estimated

        data = base64.b64decode(b64, validate=True)
        return len(data)
    except Exception:
        return None


def _is_email(value: str) -> bool:
    return bool(EMAIL_PATTERN.match(value))


def _is_phone(value: str) -> bool:
    return bool(PHONE_PATTERN.match(value))


def sanitize_text(text: str) -> str:
    """
    清理廣告文字輸入：
    - 移除控制字元（保留換行）
    - 截斷到最大長度
    - 首尾去空白
    """
    if not text:
        return ""
    # 移除除 \n \t 之外的控制字元
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    cleaned = cleaned.strip()
    if len(cleaned) > MAX_TEXT_LENGTH:
        cleaned = cleaned[:MAX_TEXT_LENGTH]
    return cleaned


def mask_api_key(key: str) -> str:
    """
    遮蔽 API Key，僅顯示前 4 碼與後 4 碼，供 log 使用。
    例如："sk-ant-abc123xyz" → "sk-a…xyz"
    """
    if not key or len(key) < 10:
        return "***"
    return key[:4] + "…" + key[-4:]
