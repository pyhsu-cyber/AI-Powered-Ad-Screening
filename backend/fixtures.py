"""
fixtures.py — 測試假資料

提供三種場景的完整假資料，供 Unit Test、E2E Test、UAT 使用：

  FIXTURE_HIGH_RISK   — 高風險：同時含「醫療效能」與「誇大不實」
  FIXTURE_MEDIUM_RISK — 中風險：只有「誇大不實」
  FIXTURE_NO_VIOLATION — 無違規：正常廣告文案

每個 fixture 包含：
  - request:  AnalyzeRequest（模擬前端送出的請求）
  - response: AnalyzeResponse（模擬後端回傳的結果）
  - complaint: ComplaintRequest（模擬使用者填寫的陳情信欄位）
"""

from datetime import date

from .schema import (
    AnalyzeRequest, AnalyzeResponse, AnalysisMode,
    ComplaintRequest, Violation, ViolationType, Confidence,
    LawReference, ProductType, RiskLevel
)

# ── 共用法條物件 ──────────────────────────────────────────

LAW_FSA_28_1 = LawReference(
    id="fsa-28-1",
    law_name="食品安全衛生管理法",
    article="第28條第1項",
    summary="食品、食品添加物等，其標示、宣傳或廣告，不得有不實、誇張或易生誤解之情形。",
    penalty="依同法第45條第1項，處新臺幣4萬元以上400萬元以下罰鍰。",
    url="https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0040001&flno=28"
)

LAW_FSA_28_2 = LawReference(
    id="fsa-28-2",
    law_name="食品安全衛生管理法",
    article="第28條第2項",
    summary="食品不得為醫療效能之標示、宣傳或廣告。",
    penalty="依同法第45條第1項，處新臺幣60萬元以上500萬元以下罰鍰。",
    url="https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0040001&flno=28"
)

LAW_COS_10_1 = LawReference(
    id="cos-10-1",
    law_name="化粧品衛生安全管理法",
    article="第10條第1項",
    summary="化粧品之標示、宣傳及廣告內容，不得有虛偽或誇大之情事。",
    penalty="依同法第20條第1項，處新臺幣4萬元以上20萬元以下罰鍰。",
    url="https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0030013&flno=10"
)

LAW_COS_10_2 = LawReference(
    id="cos-10-2",
    law_name="化粧品衛生安全管理法",
    article="第10條第2項",
    summary="化粧品不得為醫療效能之標示、宣傳或廣告。",
    penalty="依同法第20條第1項，處新臺幣60萬元以上500萬元以下罰鍰。",
    url="https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0030013&flno=10"
)

LAW_HF_14_2 = LawReference(
    id="hf-14-2",
    law_name="健康食品管理法",
    article="第14條第2項",
    summary="健康食品之標示或廣告，不得涉及醫療效能之內容。",
    penalty="依同法第24條規定處罰。",
    url="https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0040012&flno=14"
)


# ── 場景一：高風險（醫療效能 + 誇大不實） ─────────────────

FIXTURE_HIGH_RISK = {
    "label": "高風險 — 保健食品宣稱治療、逆齡",

    "request": AnalyzeRequest(
        text=(
            "【超級免疫元素膠囊】全新第三代配方！\n"
            "✅ 7天有效降血糖、降血壓，臨床實證\n"
            "✅ 根治慢性發炎，消除腫瘤細胞活性\n"
            "✅ 逆齡抗老，再生細胞，百分百有效\n"
            "限時買2送1，現貨只剩最後50盒！"
        ),
        image_base64=None,
        media_type=None
    ),

    "response": AnalyzeResponse(
        mode=AnalysisMode.FREE,
        product_name="超級免疫元素膠囊",
        product_type=ProductType.HEALTH_FOOD,
        ad_text=(
            "【超級免疫元素膠囊】全新第三代配方！\n"
            "✅ 7天有效降血糖、降血壓，臨床實證\n"
            "✅ 根治慢性發炎，消除腫瘤細胞活性\n"
            "✅ 逆齡抗老，再生細胞，百分百有效\n"
            "限時買2送1，現貨只剩最後50盒！"
        ),
        risk_level=RiskLevel.HIGH,
        overall_assessment=(
            "廣告宣稱具有降血糖、降血壓、消除腫瘤等醫療效能，"
            "同時使用「百分百有效」、「逆齡」等誇大用語，"
            "涉嫌違反食品安全衛生管理法及健康食品管理法相關規定，風險等級：高。"
        ),
        violations=[
            Violation(
                quote="7天有效降血糖、降血壓，臨床實證",
                violation_type=ViolationType.MEDICAL,
                reason="宣稱降血糖、降血壓屬醫療效能，且使用「臨床實證」暗示經醫學驗證，食品不得為此類宣傳。",
                law=LAW_FSA_28_2,
                confidence=Confidence.HIGH
            ),
            Violation(
                quote="根治慢性發炎，消除腫瘤細胞活性",
                violation_type=ViolationType.MEDICAL,
                reason="「根治」、「消除腫瘤」明確宣稱醫療效果，屬食品廣告嚴格禁止之內容。",
                law=LAW_HF_14_2,
                confidence=Confidence.HIGH
            ),
            Violation(
                quote="逆齡抗老，再生細胞，百分百有效",
                violation_type=ViolationType.EXAGGERATION,
                reason="「逆齡」、「再生細胞」為誇大宣傳，「百分百有效」屬絕對性保證用語，均違反廣告不得有誇張情形的規定。",
                law=LAW_FSA_28_1,
                confidence=Confidence.HIGH
            ),
        ]
    ),

    "complaint": ComplaintRequest(
        complainant_name="王小明",
        complainant_contact="0912-345-678",
        authority="臺北市政府衛生局",
        product_name="超級免疫元素膠囊",
        product_type="健康食品",
        platform="Facebook",
        ad_url="https://www.facebook.com/example/posts/123456",
        found_date=date(2026, 8, 24),
        has_screenshot=True
    )
}


# ── 場景二：中風險（只有誇大不實） ────────────────────────

FIXTURE_MEDIUM_RISK = {
    "label": "中風險 — 美白化粧品誇大功效",

    "request": AnalyzeRequest(
        text=(
            "【白雪公主淡斑精華】\n"
            "一抹即白！7天天天白一階\n"
            "醫美級配方，燃脂排毒雙效合一\n"
            "獨家專利，效果保證，不白退費"
        ),
        image_base64=None,
        media_type=None
    ),

    "response": AnalyzeResponse(
        mode=AnalysisMode.FREE,
        product_name="白雪公主淡斑精華",
        product_type=ProductType.COSMETIC,
        ad_text=(
            "【白雪公主淡斑精華】\n"
            "一抹即白！7天天天白一階\n"
            "醫美級配方，燃脂排毒雙效合一\n"
            "獨家專利，效果保證，不白退費"
        ),
        risk_level=RiskLevel.MEDIUM,
        overall_assessment=(
            "廣告使用「一抹即白」、「7天白一階」、「醫美級」等誇大用語，"
            "「燃脂排毒」超出化粧品功能範圍，涉嫌違反化粧品衛生安全管理法，風險等級：中。"
        ),
        violations=[
            Violation(
                quote="一抹即白！7天天天白一階",
                violation_type=ViolationType.EXAGGERATION,
                reason="宣稱立即且快速的美白效果屬誇大宣傳，化粧品不得有虛偽或誇大之情事。",
                law=LAW_COS_10_1,
                confidence=Confidence.HIGH
            ),
            Violation(
                quote="醫美級配方，燃脂排毒雙效合一",
                violation_type=ViolationType.EXAGGERATION,
                reason="「醫美級」暗示具有醫療等級效果；「燃脂排毒」超越化粧品正常功能範圍，屬誇大宣傳。",
                law=LAW_COS_10_1,
                confidence=Confidence.MEDIUM
            ),
        ]
    ),

    "complaint": ComplaintRequest(
        complainant_name="李美華",
        complainant_contact="test@example.com",
        authority="新北市政府衛生局",
        product_name="白雪公主淡斑精華",
        product_type="化粧品",
        platform="Instagram",
        ad_url="https://www.instagram.com/p/example123",
        found_date=date(2026, 8, 20),
        has_screenshot=True
    )
}


# ── 場景三：無違規 ─────────────────────────────────────────

FIXTURE_NO_VIOLATION = {
    "label": "無違規 — 符合規定的食品廣告",

    "request": AnalyzeRequest(
        text=(
            "【田園有機燕麥片】\n"
            "精選台灣有機燕麥，無農藥殘留認證\n"
            "富含膳食纖維，口感香濃\n"
            "適合全家大小，每日早餐好選擇\n"
            "淨重 500g，保存期限 12 個月"
        ),
        image_base64=None,
        media_type=None
    ),

    "response": AnalyzeResponse(
        mode=AnalysisMode.FREE,
        product_name="田園有機燕麥片",
        product_type=ProductType.FOOD,
        ad_text=(
            "【田園有機燕麥片】\n"
            "精選台灣有機燕麥，無農藥殘留認證\n"
            "富含膳食纖維，口感香濃\n"
            "適合全家大小，每日早餐好選擇\n"
            "淨重 500g，保存期限 12 個月"
        ),
        risk_level=RiskLevel.NONE,
        overall_assessment="廣告用語屬正常商業宣傳範圍，未發現明顯違規字句。",
        violations=[]
    ),

    "complaint": ComplaintRequest(
        complainant_name="陳大華",
        complainant_contact="0988-111-222",
        authority="臺中市政府衛生局",
        product_name="田園有機燕麥片",
        product_type="食品",
        platform="官方網站",
        ad_url="https://example.com/products/oats",
        found_date=date(2026, 8, 15),
        has_screenshot=False
    )
}


# ── 邊界測試假資料 ─────────────────────────────────────────

FIXTURE_EDGE_CASES = {
    "empty_text": AnalyzeRequest(text="", image_base64=None, media_type=None),
    "text_too_long": AnalyzeRequest(text="違規廣告 " * 5000, image_base64=None, media_type=None),
    "invalid_mime": AnalyzeRequest(
        text="測試", image_base64="dGVzdA==", media_type="application/pdf"
    ),
    "invalid_base64": AnalyzeRequest(
        text="測試", image_base64="not-valid-base64!!!", media_type="image/jpeg"
    ),
    "missing_name": ComplaintRequest(
        complainant_name="",
        complainant_contact="0912-345-678"
    ),
    "invalid_email": ComplaintRequest(
        complainant_name="測試用戶",
        complainant_contact="not-an-email"
    ),
    "invalid_url": ComplaintRequest(
        complainant_name="測試用戶",
        complainant_contact="0912-345-678",
        ad_url="not-a-url"
    ),
}

# ── 所有 fixtures 清單（方便測試迭代） ────────────────────

ALL_FIXTURES = [FIXTURE_HIGH_RISK, FIXTURE_MEDIUM_RISK, FIXTURE_NO_VIOLATION]
