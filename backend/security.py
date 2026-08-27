"""
security.py — 安全機制

涵蓋四個面向：
  1. API Key 驗證  — require_api_key decorator
  2. 速率限制      — RateLimiter（in-memory，無需 Redis）
  3. 資料遮蔽      — mask_sensitive_fields()（回應 / log 用）
  4. 輸入檢查      — check_content_type()、strip_dangerous_patterns()

設計原則：
  - 純 Python 標準庫 + Flask，無額外依賴
  - 速率限制使用 sliding-window（滑動視窗），比 fixed-window 更準確
  - API Key 以環境變數配置，不寫死在程式碼中
  - 遮蔽函式不修改原始物件，回傳新 dict
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import logging
import os
import re
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Tuple

from flask import request, g

from .schema import ErrorCode

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# 1. API Key 驗證
# ══════════════════════════════════════════════════════════

# 從環境變數讀取允許的 API Key 清單（逗號分隔）
# 例如：API_KEYS=key-abc123,key-xyz789
_RAW_KEYS = os.environ.get("API_KEYS", "").strip()
_ALLOWED_KEYS: frozenset = frozenset(
    k.strip() for k in _RAW_KEYS.split(",") if k.strip()
) if _RAW_KEYS else frozenset()

# 是否強制啟用 API Key 驗證（預設：有設定 API_KEYS 環境變數才啟用）
API_KEY_REQUIRED: bool = bool(_ALLOWED_KEYS)


def _get_api_key_from_request() -> Optional[str]:
    """
    從請求中取出 API Key。
    優先順序：
      1. Header X-API-Key
      2. JSON body 的 api_key 欄位
    """
    key = request.headers.get("X-API-Key", "").strip()
    if not key and request.is_json:
        body = request.get_json(silent=True) or {}
        key = (body.get("api_key") or "").strip()
    return key or None


def _verify_api_key(key: str) -> bool:
    """
    使用 hmac.compare_digest 做常數時間比對，防止 timing attack。
    """
    if not _ALLOWED_KEYS:
        return True  # 未設定 API_KEYS → 開放存取
    return any(
        hmac.compare_digest(key.encode(), allowed.encode())
        for allowed in _ALLOWED_KEYS
    )


def require_api_key(f: Callable) -> Callable:
    """
    Decorator：驗證 API Key。
    未設定 API_KEYS 環境變數時自動跳過（開放模式）。

    用法：
        @app.route("/api/analyze", methods=["POST"])
        @require_api_key
        def analyze(): ...
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not API_KEY_REQUIRED:
            return f(*args, **kwargs)

        key = _get_api_key_from_request()
        if not key:
            logger.warning("API Key 缺失，IP=%s", _get_client_ip())
            from flask import jsonify
            return jsonify({
                "code": ErrorCode.MISSING_API_KEY,
                "message": "請提供 API Key（Header: X-API-Key 或 body.api_key）。",
            }), 401

        if not _verify_api_key(key):
            logger.warning("API Key 無效，IP=%s，key_prefix=%s", _get_client_ip(), key[:4])
            from flask import jsonify
            return jsonify({
                "code": ErrorCode.INVALID_API_KEY,
                "message": "API Key 無效，請確認後重試。",
            }), 401

        # 將遮蔽後的 key 存入 g，方便 log 使用
        g.api_key_masked = mask_api_key(key)
        logger.debug("API Key 驗證通過，key=%s", g.api_key_masked)
        return f(*args, **kwargs)
    return wrapper


# ══════════════════════════════════════════════════════════
# 2. 速率限制（Sliding Window，in-memory）
# ══════════════════════════════════════════════════════════

class RateLimiter:
    """
    基於滑動視窗的 in-memory 速率限制器。

    Parameters
    ----------
    max_calls : int
        視窗內允許的最大請求數
    window_seconds : int
        視窗大小（秒）

    使用方式：
        limiter = RateLimiter(max_calls=10, window_seconds=60)

        @app.route("/api/analyze", methods=["POST"])
        @limiter.limit
        def analyze(): ...
    """

    def __init__(self, max_calls: int = 10, window_seconds: int = 60):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._store: Dict[str, deque] = defaultdict(deque)
        self._lock = Lock()

    def is_allowed(self, key: str) -> Tuple[bool, int]:
        """
        檢查 key 是否在速率限制內。

        Returns
        -------
        (allowed, remaining)
            allowed   : 是否允許此請求
            remaining : 視窗內剩餘可用次數
        """
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            dq = self._store[key]
            # 移除視窗外的舊記錄
            while dq and dq[0] <= cutoff:
                dq.popleft()

            count = len(dq)
            if count >= self.max_calls:
                return False, 0

            dq.append(now)
            return True, self.max_calls - count - 1

    def limit(self, f: Callable) -> Callable:
        """Decorator：套用速率限制，超過時回傳 429。"""
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            ip = _get_client_ip()
            allowed, remaining = self.is_allowed(ip)

            if not allowed:
                logger.warning("速率限制觸發，IP=%s", ip)
                from flask import jsonify
                resp = jsonify({
                    "code": ErrorCode.RATE_LIMIT_EXCEEDED,
                    "message": f"請求過於頻繁，每 {self.window_seconds} 秒最多 {self.max_calls} 次，請稍後再試。",
                })
                resp.headers["Retry-After"] = str(self.window_seconds)
                resp.headers["X-RateLimit-Limit"] = str(self.max_calls)
                resp.headers["X-RateLimit-Remaining"] = "0"
                return resp, 429

            response = f(*args, **kwargs)
            # 將速率限制 header 加到成功回應
            _add_rate_limit_headers(response, self.max_calls, remaining)
            return response
        return wrapper

    def reset(self, key: str = None) -> None:
        """清除速率限制記錄（供測試使用）。"""
        with self._lock:
            if key:
                self._store.pop(key, None)
            else:
                self._store.clear()


def _add_rate_limit_headers(response, limit: int, remaining: int) -> None:
    """將速率限制資訊加入回應 header。"""
    try:
        if isinstance(response, tuple):
            resp_obj = response[0]
        else:
            resp_obj = response
        resp_obj.headers["X-RateLimit-Limit"] = str(limit)
        resp_obj.headers["X-RateLimit-Remaining"] = str(remaining)
    except Exception:
        pass  # header 寫入失敗不影響主流程


# 預設的速率限制器實例（/api/analyze 用）
analyze_limiter = RateLimiter(
    max_calls=int(os.environ.get("RATE_LIMIT_CALLS", "10")),
    window_seconds=int(os.environ.get("RATE_LIMIT_WINDOW", "60")),
)

# /api/status 較寬鬆
status_limiter = RateLimiter(max_calls=60, window_seconds=60)


# ══════════════════════════════════════════════════════════
# 3. 資料遮蔽
# ══════════════════════════════════════════════════════════

# 這些欄位的值在 log / 回應中會被遮蔽
# 查找一律用 k.lower()，所以這裡的鍵必須全部小寫 ——
# 曾經寫成 "fName" / "fContact"（前端真實欄位名），結果檢舉人姓名與
# 聯絡方式從來沒有被遮蔽過。
_SENSITIVE_FIELDS = frozenset({
    "api_key", "image_base64", "complainant_name",
    "complainant_contact", "fname", "fcontact",
})

# 可能含個資的 Header
_SENSITIVE_HEADERS = frozenset({
    "x-api-key", "authorization", "cookie",
})


def mask_api_key(key: str) -> str:
    """
    遮蔽 API Key，只顯示前 4 碼與後 4 碼。
    例如："sk-ant-abc123xyz" → "sk-a…xyz"
    """
    if not key or len(key) < 10:
        return "***"
    return key[:4] + "…" + key[-4:]


def mask_sensitive_fields(data: dict, redact_image: bool = True) -> dict:
    """
    回傳資料的遮蔽版本（不修改原始 dict）。

    Parameters
    ----------
    data : dict
        原始資料（如請求 body）
    redact_image : bool
        是否遮蔽 image_base64（預設 True，避免大量資料寫入 log）

    Returns
    -------
    dict
        敏感欄位被替換為 "[REDACTED]" 的新 dict
    """
    result = {}
    for k, v in data.items():
        key_lower = k.lower()
        if key_lower in _SENSITIVE_FIELDS:
            if key_lower == "image_base64" and redact_image and v:
                # 保留長度資訊，方便除錯
                size = len(v) if isinstance(v, str) else 0
                result[k] = f"[BASE64 ~{size // 1024}KB]"
            elif key_lower in ("api_key",) and isinstance(v, str):
                result[k] = mask_api_key(v)
            else:
                result[k] = "[REDACTED]"
        elif isinstance(v, dict):
            result[k] = mask_sensitive_fields(v, redact_image)
        elif isinstance(v, list):
            result[k] = [
                mask_sensitive_fields(item, redact_image) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            result[k] = v
    return result


def log_request(endpoint: str) -> None:
    """記錄請求（遮蔽敏感資料）。"""
    body = {}
    if request.is_json:
        body = request.get_json(silent=True) or {}

    logger.info(
        "[%s] %s %s | IP=%s | body_keys=%s",
        endpoint,
        request.method,
        request.path,
        _get_client_ip(),
        list(mask_sensitive_fields(body).keys()),
    )


# ══════════════════════════════════════════════════════════
# 4. 輸入檢查（深度防禦，補充 validators.py）
# ══════════════════════════════════════════════════════════

# 可能用於注入攻擊的模式（針對文字欄位）
_DANGEROUS_PATTERNS: List[re.Pattern] = [
    re.compile(r'<script[^>]*>', re.IGNORECASE),           # XSS
    re.compile(r'javascript\s*:', re.IGNORECASE),           # JS 協議
    re.compile(r'on\w+\s*=', re.IGNORECASE),               # 事件屬性
    re.compile(r'data\s*:\s*text/html', re.IGNORECASE),    # data URI
]

# 廣告文字不應包含的 null byte 或過長的重複字元
_NULL_BYTE = re.compile(r'\x00')
_REPEATED_CHAR = re.compile(r'(.)\1{500,}')  # 同一字元重複 500 次以上


def strip_dangerous_patterns(text: str) -> Tuple[str, List[str]]:
    """
    掃描並移除廣告文字中的危險模式。

    Returns
    -------
    (cleaned_text, warnings)
        cleaned_text : 清理後的文字
        warnings     : 偵測到的問題描述清單
    """
    if not text:
        return text, []

    warnings: List[str] = []
    cleaned = text

    # Null byte
    if _NULL_BYTE.search(cleaned):
        cleaned = _NULL_BYTE.sub("", cleaned)
        warnings.append("偵測到 null byte，已移除。")

    # 過長重複字元（可能是 fuzzing）
    if _REPEATED_CHAR.search(cleaned):
        cleaned = _REPEATED_CHAR.sub(lambda m: m.group(1) * 10, cleaned)
        warnings.append("偵測到異常重複字元，已截斷。")

    # XSS / 注入模式（在廣告文字中不應出現，記錄但不完全移除）
    for pat in _DANGEROUS_PATTERNS:
        if pat.search(cleaned):
            warnings.append(f"廣告文字包含可疑模式（{pat.pattern[:30]}），請確認內容正確。")
            cleaned = pat.sub("", cleaned)

    if warnings:
        logger.warning("輸入清理警告：%s", "; ".join(warnings))

    return cleaned, warnings


def check_content_type(f: Callable) -> Callable:
    """
    Decorator：確保請求的 Content-Type 為 application/json。
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if request.method in ("POST", "PUT", "PATCH"):
            ct = request.content_type or ""
            if "application/json" not in ct.lower():
                from flask import jsonify
                return jsonify({
                    "code": "INVALID_CONTENT_TYPE",
                    "message": "請求必須使用 Content-Type: application/json。",
                }), 415
        return f(*args, **kwargs)
    return wrapper


def add_security_headers(response):
    """
    Flask after_request hook：加入安全相關 HTTP Header。
    """
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # API 回應不應被快取
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


# ══════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════

def _get_client_ip() -> str:
    """取得客戶端 IP，考慮反向代理的 X-Forwarded-For。"""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        # 取第一個 IP（最原始的客戶端）
        ip = forwarded.split(",")[0].strip()
        # 基本驗證：只允許 IPv4/IPv6 格式
        if re.match(r'^[\d.:a-fA-F]+$', ip):
            return ip
    return request.remote_addr or "unknown"


def hash_ip(ip: str) -> str:
    """
    對 IP 做單向雜湊，用於 log（避免儲存真實 IP，符合個資保護原則）。
    """
    return hashlib.sha256(ip.encode()).hexdigest()[:12]
