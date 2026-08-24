"""
analyzer.py — 違規關鍵字比對引擎（免費模式）

職責：
  1. 載入 regulations.json
  2. 對廣告文字進行關鍵字掃描
  3. 回傳 AnalyzeResponse（符合 schema.py 定義）

設計原則：
  - 純函式，不依賴外部服務，可完整單元測試
  - 關鍵字清單從 regulations.json 讀取，不硬編碼
  - 比對時忽略半全形差異、空白
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .schema import (
    AnalysisMode, AnalyzeResponse, Confidence, LawReference,
    ProductType, RiskLevel, Violation, ViolationType,
)

# ── 法規資料載入 ───────────────────────────────────────────

_REGULATIONS_PATH = Path(__file__).parent.parent / "regulations.json"
_reg_cache: Optional[dict] = None


def _load_regulations() -> dict:
    global _reg_cache
    if _reg_cache is None:
        with open(_REGULATIONS_PATH, encoding="utf-8") as f:
            _reg_cache = json.load(f)
    return _reg_cache


def _get_law_map() -> Dict[str, LawReference]:
    """將 regulations.json 的 laws 陣列轉為 id → LawReference dict。"""
    data = _load_regulations()
    return {
        law["id"]: LawReference(
            id=law["id"],
            law_name=law["law_name"],
            article=law["article"],
            summary=law["summary"],
            penalty=law["penalty"],
            url=law["url"],
        )
        for law in data.get("laws", [])
    }


def _get_keywords() -> Dict[str, List[str]]:
    """回傳 demo_keywords，格式：{"medical_efficacy": [...], "exaggeration": [...]}"""
    data = _load_regulations()
    return data.get("demo_keywords", {})


# ── 文字正規化 ─────────────────────────────────────────────

_HALF_FULL_TABLE = str.maketrans(
    "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
)


def _normalize(text: str) -> str:
    """全形轉半形、移除空白，方便子字串比對。"""
    return text.translate(_HALF_FULL_TABLE).replace(" ", "").replace("\u3000", "")


# ── 產品名稱與類別推斷 ─────────────────────────────────────

_PRODUCT_TYPE_HINTS = {
    ProductType.COSMETIC:    ["精華", "乳液", "面膜", "防曬", "粉底", "口紅", "保養", "美白", "淡斑"],
    ProductType.HEALTH_FOOD: ["膠囊", "錠", "粉末", "保健", "營養", "益生菌", "膠原蛋白", "維他命", "維生素"],
    ProductType.FOOD:        ["食品", "飲料", "果汁", "茶", "咖啡", "零食", "餅乾", "燕麥"],
    ProductType.DRUG:        ["藥", "錠劑", "藥膏", "藥水"],
}


def _infer_product_type(text: str) -> ProductType:
    norm = _normalize(text)
    scores = {pt: 0 for pt in ProductType}
    for pt, hints in _PRODUCT_TYPE_HINTS.items():
        for hint in hints:
            if hint in norm:
                scores[pt] += 1
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else ProductType.UNKNOWN


def _extract_product_name(text: str) -> str:
    """嘗試從廣告文字第一行提取產品名稱。"""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "未標示"
    first = lines[0]
    # 移除常見前後綴
    first = re.sub(r"^[【\[（(]|[】\]）)]\s*$", "", first).strip()
    # 若太長（>20字）截斷
    return first[:20] if len(first) > 20 else first or "未標示"


# ── 關鍵字比對核心 ─────────────────────────────────────────

def _find_violations(text: str, law_map: Dict[str, LawReference]) -> List[Violation]:
    """
    掃描廣告文字，回傳所有命中的違規項目。

    比對策略：
      - medical_efficacy 命中 → ViolationType.MEDICAL，優先引用 fsa-28-2
      - exaggeration 命中     → ViolationType.EXAGGERATION，引用 fsa-28-1
      - 同一關鍵字只回報一次（去重）
    """
    keywords = _get_keywords()
    norm_text = _normalize(text)
    violations: List[Violation] = []
    seen_quotes: set = set()

    medical_law = law_map.get("fsa-28-2") or law_map.get("fsa-28-1")
    exag_law    = law_map.get("fsa-28-1") or next(iter(law_map.values()), None)

    for category, kw_list in keywords.items():
        is_medical = (category == "medical_efficacy")
        vtype  = ViolationType.MEDICAL if is_medical else ViolationType.EXAGGERATION
        law    = medical_law if is_medical else exag_law

        for kw in kw_list:
            norm_kw = _normalize(kw)
            if norm_kw in norm_text:
                # 找到原始文字中的實際匹配位置（還原展示用引用）
                quote = _find_original_quote(text, kw)
                if quote in seen_quotes:
                    continue
                seen_quotes.add(quote)

                reason = _make_reason(kw, vtype)
                violations.append(Violation(
                    quote=quote,
                    violation_type=vtype,
                    reason=reason,
                    law=law,
                    confidence=Confidence.HIGH,
                ))

    return violations


def _find_original_quote(text: str, keyword: str) -> str:
    """
    在原始文字中找出含關鍵字的最短句子片段（不超過 40 字）。
    找不到就直接回傳關鍵字本身。
    """
    norm_text = _normalize(text)
    norm_kw   = _normalize(keyword)
    idx = norm_text.find(norm_kw)
    if idx == -1:
        return keyword

    # 往前找句子起點（標點或換行）
    start = idx
    for sep in "，。！？、\n":
        pos = norm_text.rfind(sep, 0, idx)
        if pos != -1:
            start = max(start, pos + 1)

    # 往後找句子終點
    end = idx + len(norm_kw)
    for sep in "，。！？、\n":
        pos = norm_text.find(sep, idx + len(norm_kw))
        if pos != -1:
            end = min(end, pos)
            break

    # 對應回原始文字（norm 與 original 長度相同，因為只做替換不增刪）
    fragment = text[start:end].strip()
    return fragment[:40] if len(fragment) > 40 else fragment or keyword


def _make_reason(keyword: str, vtype: ViolationType) -> str:
    if vtype == ViolationType.MEDICAL:
        return f"廣告使用「{keyword}」，屬醫療效能宣稱，食品 / 化粧品廣告不得為此類標示或宣傳。"
    return f"廣告使用「{keyword}」，屬誇大不實用語，易使消費者產生誤解，違反廣告不得有誇張情形的規定。"


# ── 風險等級計算 ───────────────────────────────────────────

def _calc_risk(violations: List[Violation]) -> RiskLevel:
    if not violations:
        return RiskLevel.NONE
    has_medical = any(v.violation_type == ViolationType.MEDICAL for v in violations)
    if has_medical or len(violations) >= 3:
        return RiskLevel.HIGH
    if len(violations) >= 2:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _make_assessment(violations: List[Violation], risk: RiskLevel, product_name: str) -> str:
    if not violations:
        return f"廣告文字（{product_name}）未發現明顯違規字句。"
    types = set(v.violation_type for v in violations)
    parts = []
    if ViolationType.MEDICAL in types:
        parts.append("宣稱醫療效能")
    if ViolationType.EXAGGERATION in types:
        parts.append("誇大不實用語")
    return (
        f"廣告共偵測到 {len(violations)} 項疑似違規：{' 及 '.join(parts)}，"
        f"風險等級：{risk.value}。請確認分析結果並依需要提交主管機關查處。"
    )


# ── 對外主函式 ─────────────────────────────────────────────

def analyze_text(text: str) -> AnalyzeResponse:
    """
    對廣告文字執行關鍵字比對分析，回傳 AnalyzeResponse。

    Parameters
    ----------
    text : str
        已清理的廣告文字（由 validators.sanitize_text 處理過）

    Returns
    -------
    AnalyzeResponse
    """
    law_map    = _get_law_map()
    violations = _find_violations(text, law_map)
    risk       = _calc_risk(violations)
    ptype      = _infer_product_type(text)
    pname      = _extract_product_name(text)
    assessment = _make_assessment(violations, risk, pname)

    return AnalyzeResponse(
        mode=AnalysisMode.FREE,
        product_name=pname,
        product_type=ptype,
        ad_text=text,
        risk_level=risk,
        overall_assessment=assessment,
        violations=violations,
    )


def reload_regulations() -> None:
    """清除快取，強制下次呼叫重新載入 regulations.json（供測試使用）。"""
    global _reg_cache
    _reg_cache = None
