"""
app.py — Flask 主程式

啟動方式：
  python backend/app.py

或透過 Waitress（生產用）：
  waitress-serve --port=8765 backend.app:app

Endpoint：
  GET  /api/status   — 查詢系統狀態
  POST /api/analyze  — 違規廣告快篩分析
  GET  /             — 回傳 static/index.html（build.py 產生的現行版本）
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# ── 確保 backend package 可被 import ──────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.analyzer import analyze_text
from backend.ocr_runner import OcrError, is_ocr_available, run_ocr
from backend.schema import (
    AnalysisMode, AnalyzeRequest, ErrorCode, ErrorResponse, StatusResponse,
)
from backend.validators import sanitize_text, validate_analyze_request
from backend.security import (
    add_security_headers,
    analyze_limiter,
    check_content_type,
    log_request,
    require_api_key,
    status_limiter,
    strip_dangerous_patterns,
)

# ── 日誌設定 ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Flask 應用 ─────────────────────────────────────────────
_STATIC_DIR = Path(__file__).parent.parent / "static"

app = Flask(__name__, static_folder=str(_STATIC_DIR))
CORS(app, resources={r"/api/*": {"origins": "*"}})

# 從環境變數讀取設定
_ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
_DEBUG         = os.environ.get("FLASK_DEBUG", "0").strip() == "1"
_PORT          = int(os.environ.get("PORT", "8765"))

app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024  # 12 MB，含 Base64 overhead

# ── 安全 Header（所有回應都加上）─────────────────────────
app.after_request(add_security_headers)


# ══════════════════════════════════════════════════════════
# 工具：統一錯誤回應
# ══════════════════════════════════════════════════════════

def _err(code: str, message: str, http_status: int, detail: str = "") -> tuple:
    body = {"code": code, "message": message}
    if _DEBUG and detail:
        body["detail"] = detail
    return jsonify(body), http_status


# ══════════════════════════════════════════════════════════
# Endpoint：GET /api/status
# ══════════════════════════════════════════════════════════

@app.route("/api/status", methods=["GET"])
@status_limiter.limit
def status():
    """
    回傳系統狀態。

    Response 200:
      {"ai_enabled": bool, "mode": "free"|"claude", "version": "2.0.0"}
    """
    ai_enabled = bool(_ANTHROPIC_KEY)
    mode       = AnalysisMode.CLAUDE if ai_enabled else AnalysisMode.FREE

    resp = StatusResponse(
        ai_enabled=ai_enabled,
        mode=mode,
        version="2.0.0",
    )
    return jsonify(resp.to_dict()), 200


# ══════════════════════════════════════════════════════════
# Endpoint：POST /api/analyze
# ══════════════════════════════════════════════════════════

@app.route("/api/analyze", methods=["POST"])
@require_api_key
@analyze_limiter.limit
@check_content_type
def analyze():
    """
    違規廣告快篩分析。

    Request body (JSON):
      {"image_base64": "...", "media_type": "image/jpeg", "text": "..."}

    Response 200:
      AnalyzeResponse（見 api_spec.py）

    Response 4xx/5xx:
      {"code": "...", "message": "..."}
    """
    # ── 1. 記錄請求（遮蔽敏感資料）────────────────────────
    log_request("analyze")

    # ── 2. 解析 JSON ──────────────────────────────────────
    if not request.is_json:
        return _err(ErrorCode.MISSING_INPUT, "請求必須為 JSON 格式（Content-Type: application/json）", 400)

    body = request.get_json(silent=True)
    if body is None:
        return _err(ErrorCode.MISSING_INPUT, "無法解析請求 JSON，請確認格式正確。", 400)

    # ── 3. 建立 AnalyzeRequest 並驗證 ─────────────────────
    req = AnalyzeRequest(
        text          = body.get("text") or "",
        image_base64  = body.get("image_base64") or None,
        media_type    = body.get("media_type") or None,
        api_key       = body.get("api_key") or None,
    )

    ok, errors = validate_analyze_request(req)
    if not ok:
        first = errors[0]
        return _err(first["code"], first["message"], 400)

    # ── 4. 清理文字輸入（sanitize + 危險模式過濾）───────────
    clean_text = sanitize_text(req.text)
    if clean_text:
        clean_text, warnings = strip_dangerous_patterns(clean_text)
        if warnings:
            logger.warning("輸入清理警告（analyze）：%s", warnings)

    # ── 5. OCR（有圖片且文字為空時才執行）─────────────────
    ocr_text = ""
    if req.image_base64 and not clean_text:
        try:
            logger.info("執行 Windows OCR，media_type=%s", req.media_type)
            ocr_text = run_ocr(req.image_base64, req.media_type)
            logger.info("OCR 完成，字數=%d", len(ocr_text.replace(" ", "")))
        except OcrError as e:
            logger.warning("OCR 失敗：%s", e)
            # OCR 失敗時不立即中斷，讓前端知道（ad_text 為空，前端會改用瀏覽器 OCR）
            # 只有完全沒有任何文字時才回傳錯誤
            if not clean_text:
                return _err(
                    ErrorCode.OCR_FAILED,
                    f"圖片辨識失敗：{e}。請手動輸入廣告文字後再試。",
                    500,
                    detail=str(e),
                )

    # ── 6. 決定分析文字 ───────────────────────────────────
    analysis_text = clean_text or ocr_text
    if not analysis_text.strip():
        return _err(
            ErrorCode.MISSING_INPUT,
            "圖片沒有辨識出文字，請把廣告文案手動貼到廣告文字欄位後再試。",
            400,
        )

    # ── 7. 分析：Claude AI 或免費關鍵字比對 ──────────────
    try:
        if _ANTHROPIC_KEY:
            result = _analyze_with_claude(req.image_base64, req.media_type, analysis_text)
        else:
            logger.info("使用免費關鍵字比對模式")
            result = analyze_text(analysis_text)
    except ClaudeError as e:
        logger.error("Claude API 失敗：%s", e)
        return _err(ErrorCode.AI_UNAVAILABLE, f"AI 分析服務暫時不可用：{e}", 503, detail=str(e))
    except Exception as e:
        logger.exception("分析時發生未預期錯誤")
        return _err(ErrorCode.INTERNAL_ERROR, "系統發生錯誤，請重試。", 500, detail=str(e))

    return jsonify(result.to_dict()), 200


# ══════════════════════════════════════════════════════════
# Claude AI 分析（需設定 ANTHROPIC_API_KEY 環境變數）
# ══════════════════════════════════════════════════════════

class ClaudeError(Exception):
    pass


def _load_law_list() -> str:
    """產生給 Claude 用的法條清單字串。"""
    from backend.analyzer import _get_law_map
    law_map = _get_law_map()
    return "\n".join(
        f"- {lid}：《{law.law_name}》{law.article} — {law.summary}"
        for lid, law in law_map.items()
    )


def _analyze_with_claude(
    image_b64: str | None,
    media_type: str | None,
    text: str,
) -> "AnalyzeResponse":
    """
    呼叫 Anthropic Claude API 進行語意分析。
    需要 ANTHROPIC_API_KEY 環境變數。
    """
    try:
        import anthropic
    except ImportError:
        raise ClaudeError("anthropic 套件未安裝，請執行：pip install anthropic")

    from backend.analyzer import _get_law_map
    from backend.schema import (
        AnalysisMode, AnalyzeResponse, Confidence, LawReference,
        ProductType, RiskLevel, Violation, ViolationType,
    )

    law_map   = _get_law_map()
    law_list  = _load_law_list()

    prompt = f"""你是台灣食品藥物管理法規稽查專員。請分析以下廣告，找出違反下列法規的宣傳字句。

可引用的法條：
{law_list}

請只輸出 JSON，不要有任何說明文字，格式如下：
{{"product_name":"...","product_type":"食品／健康食品／化粧品／藥品／醫療器材／其他／無法判定","ad_text":"...","risk_level":"高／中／低／無明顯違規","overall_assessment":"...","violations":[{{"quote":"...","violation_type":"誇大不實或宣稱醫療效能","reason":"...","law_id":"...","confidence":"高／中／低"}}]}}

廣告文字：
{text}"""

    content = [{"type": "text", "text": prompt}]
    if image_b64 and media_type:
        content.insert(0, {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": image_b64},
        })

    client = anthropic.Anthropic(api_key=_ANTHROPIC_KEY)
    try:
        msg = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=2048,
            messages=[{"role": "user", "content": content}],
        )
    except Exception as e:
        raise ClaudeError(str(e)) from e

    raw = msg.content[0].text.strip()
    raw = raw.lstrip("```json").lstrip("```").rstrip("```").strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ClaudeError(f"Claude 回傳非 JSON：{raw[:200]}") from e

    # 組裝 AnalyzeResponse
    vios = []
    for v in data.get("violations", []):
        law = law_map.get(v.get("law_id", ""), law_map.get("fsa-28-1"))
        vtype = ViolationType.MEDICAL if "醫療" in v.get("violation_type", "") else ViolationType.EXAGGERATION
        conf_map = {"高": Confidence.HIGH, "中": Confidence.MEDIUM, "低": Confidence.LOW}
        vios.append(Violation(
            quote=v.get("quote", ""),
            violation_type=vtype,
            reason=v.get("reason", ""),
            law=law,
            confidence=conf_map.get(v.get("confidence", "中"), Confidence.MEDIUM),
        ))

    risk_map = {"高": RiskLevel.HIGH, "中": RiskLevel.MEDIUM, "低": RiskLevel.LOW, "無明顯違規": RiskLevel.NONE}
    ptype_map = {pt.value: pt for pt in ProductType}

    return AnalyzeResponse(
        mode=AnalysisMode.CLAUDE,
        product_name=data.get("product_name", "未標示"),
        product_type=ptype_map.get(data.get("product_type", ""), ProductType.UNKNOWN),
        ad_text=data.get("ad_text", text),
        risk_level=risk_map.get(data.get("risk_level", ""), RiskLevel.NONE),
        overall_assessment=data.get("overall_assessment", ""),
        violations=vios,
    )


# ══════════════════════════════════════════════════════════
# 靜態檔案（開發用）
# ══════════════════════════════════════════════════════════

@app.route("/")
def index():
    """回傳前端頁面。

    一律回 static/index.html —— 那是 實作作業/build.py 產生的現行版本。
    （曾經優先載入 index_v2.html，但那是 v3 世代的殘檔，缺少依產品類別切換法條、
      藥品／醫療器材法條與背景交叉比對，接上去會讓 UI 靜默回退。）
    """
    return send_from_directory(str(_STATIC_DIR), "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(str(_STATIC_DIR), filename)


# ══════════════════════════════════════════════════════════
# 錯誤處理
# ══════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(e):
    return _err("NOT_FOUND", "找不到請求的資源。", 404)


@app.errorhandler(405)
def method_not_allowed(e):
    return _err("METHOD_NOT_ALLOWED", "不支援的 HTTP 方法。", 405)


@app.errorhandler(413)
def payload_too_large(e):
    return _err(ErrorCode.IMAGE_TOO_LARGE, "請求本體超過大小上限（12 MB），請壓縮圖片後再試。", 413)


@app.errorhandler(500)
def internal_error(e):
    logger.exception("未處理的伺服器錯誤")
    return _err(ErrorCode.INTERNAL_ERROR, "系統發生錯誤，請重試。", 500)


# ══════════════════════════════════════════════════════════
# 啟動
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    logger.info("啟動違規廣告快篩 API 伺服器，port=%d, debug=%s", _PORT, _DEBUG)
    logger.info("AI 模式：%s", "Claude" if _ANTHROPIC_KEY else "免費關鍵字比對")
    logger.info("靜態目錄：%s", _STATIC_DIR)
    app.run(host="127.0.0.1", port=_PORT, debug=_DEBUG)
