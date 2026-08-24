"""
schema.py — 違規廣告快篩系統資料模型定義

資料流：
  AnalyzeRequest
      ↓  OCR + 規則比對 / AI 分析
  AnalyzeResponse
      ↓  使用者填寫陳情信欄位
  ComplaintRequest
      ↓  生成
  ComplaintLetter

所有模型皆使用標準 dataclass，不依賴任何 ORM，
方便直接 JSON 序列化，也便於單元測試。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date
from enum import Enum
from typing import List, Optional


# ── 枚舉值 ─────────────────────────────────────────────

class ProductType(str, Enum):
    """產品類別"""
    FOOD          = "食品"
    HEALTH_FOOD   = "健康食品"
    COSMETIC      = "化粧品"
    DRUG          = "藥品"
    MEDICAL_DEVICE = "醫療器材"
    OTHER         = "其他"
    UNKNOWN       = "無法判定"


class RiskLevel(str, Enum):
    """違規風險等級"""
    HIGH    = "高"
    MEDIUM  = "中"
    LOW     = "低"
    NONE    = "無明顯違規"


class ViolationType(str, Enum):
    """違規類型"""
    EXAGGERATION = "誇大不實"
    MEDICAL      = "宣稱醫療效能"


class Confidence(str, Enum):
    """AI 判斷信心程度"""
    HIGH   = "高"
    MEDIUM = "中"
    LOW    = "低"


class AnalysisMode(str, Enum):
    """分析模式"""
    FREE    = "free"       # 關鍵字比對
    GEMINI  = "gemini"     # Google Gemini 免費額度
    CLAUDE  = "claude"     # Anthropic Claude（付費）


# ── 法規條文 ────────────────────────────────────────────

@dataclass
class LawReference:
    """法規條文引用"""
    id: str                # e.g. "fsa-28-1"
    law_name: str          # e.g. "食品安全衛生管理法"
    article: str           # e.g. "第28條第1項"
    summary: str           # 條文摘要
    penalty: str           # 罰則說明
    url: str               # 全國法規資料庫連結

    def to_dict(self) -> dict:
        return asdict(self)


# ── 違規項目 ────────────────────────────────────────────

@dataclass
class Violation:
    """單一違規項目"""
    quote: str                          # 廣告中的原始字句（逐字引用）
    violation_type: ViolationType       # 違規類型
    reason: str                         # 違規原因說明
    law: LawReference                   # 引用法條
    confidence: Confidence = Confidence.MEDIUM  # AI 信心程度

    def to_dict(self) -> dict:
        d = asdict(self)
        d['violation_type'] = self.violation_type.value
        d['confidence'] = self.confidence.value
        return d


# ── API 請求／回應 ───────────────────────────────────────

@dataclass
class AnalyzeRequest:
    """
    POST /api/analyze 請求本體

    欄位說明：
      image_base64  圖片 Base64 編碼（純資料，不含 data:image/… 前綴）
      media_type    圖片 MIME type，例如 image/jpeg
      text          廣告文字（可與圖片擇一，或同時提供）
      api_key       選填，呼叫端提供的 API Key（安全切片時會強制驗證）

    驗證規則：
      - image_base64 與 text 至少一項不為空
      - image_base64 不為空時，media_type 必須提供且為允許的 MIME type
      - text 不為空時，長度不超過 MAX_TEXT_LENGTH
      - image_base64 解碼後不超過 MAX_IMAGE_BYTES
    """
    text: str = ""
    image_base64: Optional[str] = None
    media_type: Optional[str] = None
    api_key: Optional[str] = None

    # 驗證常數（驗證器會引用這裡）
    MAX_TEXT_LENGTH: int = field(default=20_000, init=False, repr=False)
    ALLOWED_MIME_TYPES: tuple = field(
        default=('image/jpeg', 'image/png', 'image/webp', 'image/gif'),
        init=False, repr=False
    )
    MAX_IMAGE_BYTES: int = field(default=10 * 1024 * 1024, init=False, repr=False)  # 10 MB


@dataclass
class AnalyzeResponse:
    """
    POST /api/analyze 回應本體

    欄位說明：
      mode              實際使用的分析模式
      product_name      廣告中辨識到的產品名稱
      product_type      產品類別
      ad_text           廣告文字（OCR 結果或使用者提供）
      risk_level        整體違規風險等級
      overall_assessment  整體評估說明
      violations        違規項目清單（可能為空）
    """
    mode: AnalysisMode
    product_name: str
    product_type: ProductType
    ad_text: str
    risk_level: RiskLevel
    overall_assessment: str
    violations: List[Violation] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "product_name": self.product_name,
            "product_type": self.product_type.value,
            "ad_text": self.ad_text,
            "risk_level": self.risk_level.value,
            "overall_assessment": self.overall_assessment,
            "violations": [v.to_dict() for v in self.violations],
        }


@dataclass
class StatusResponse:
    """GET /api/status 回應"""
    ai_enabled: bool
    mode: AnalysisMode
    version: str = "2.0.0"

    def to_dict(self) -> dict:
        return {
            "ai_enabled": self.ai_enabled,
            "mode": self.mode.value,
            "version": self.version,
        }


# ── 陳情信相關 ───────────────────────────────────────────

@dataclass
class ComplaintRequest:
    """
    陳情信生成所需的使用者填寫欄位

    驗證規則：
      - complainant_name    必填，1–50 字
      - complainant_contact 必填，電話或 Email 格式
      - ad_url              選填，若填寫需符合 URL 格式
      - found_date          選填，不可超過今天
    """
    complainant_name: str               # 檢舉人姓名（必填）
    complainant_contact: str            # 聯絡方式：電話或 Email（必填）
    authority: str = "臺北市政府衛生局" # 受文機關
    product_name: str = ""              # 產品名稱
    product_type: str = "無法判定"      # 產品類別
    platform: str = ""                  # 廣告刊登平台
    ad_url: str = ""                    # 廣告網址
    found_date: Optional[date] = None   # 發現日期
    has_screenshot: bool = False        # 是否附截圖


@dataclass
class ComplaintLetter:
    """生成完成的陳情信"""
    body: str                           # 信件全文
    generated_at: str                   # 生成時間（ISO 格式）
    authority: str                      # 受文機關
    product_name: str

    def to_dict(self) -> dict:
        return asdict(self)


# ── 錯誤回應 ─────────────────────────────────────────────

@dataclass
class ErrorResponse:
    """
    統一錯誤回應格式

    code    機器可讀的錯誤代碼（見下方 ErrorCode）
    message 給使用者看的說明
    detail  給開發者看的詳細資訊（正式環境不回傳）
    """
    code: str
    message: str
    detail: Optional[str] = None

    def to_dict(self, include_detail: bool = False) -> dict:
        d = {"code": self.code, "message": self.message}
        if include_detail and self.detail:
            d["detail"] = self.detail
        return d


class ErrorCode:
    """統一錯誤代碼表"""
    # 輸入驗證
    MISSING_INPUT        = "MISSING_INPUT"        # image_base64 和 text 皆為空
    TEXT_TOO_LONG        = "TEXT_TOO_LONG"         # 文字超過長度上限
    INVALID_MIME         = "INVALID_MIME_TYPE"     # 不支援的圖片格式
    IMAGE_TOO_LARGE      = "IMAGE_TOO_LARGE"       # 圖片超過大小上限
    INVALID_IMAGE_DATA   = "INVALID_IMAGE_DATA"    # Base64 解碼失敗
    INVALID_URL          = "INVALID_URL"           # 廣告網址格式錯誤
    MISSING_NAME         = "MISSING_NAME"          # 缺少檢舉人姓名
    MISSING_CONTACT      = "MISSING_CONTACT"       # 缺少聯絡方式
    # 安全
    MISSING_API_KEY      = "MISSING_API_KEY"       # 未提供 API Key
    INVALID_API_KEY      = "INVALID_API_KEY"       # API Key 無效
    RATE_LIMIT_EXCEEDED  = "RATE_LIMIT_EXCEEDED"   # 超過速率限制
    # 伺服器
    OCR_FAILED           = "OCR_FAILED"            # OCR 失敗
    AI_UNAVAILABLE       = "AI_UNAVAILABLE"        # AI 服務不可用
    INTERNAL_ERROR       = "INTERNAL_ERROR"        # 內部錯誤
