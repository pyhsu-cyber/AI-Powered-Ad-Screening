# Karpathy Guidelines

Andrej Karpathy 的軟體開發哲學：盡量少寫程式碼，只解決當前問題。

---

## 核心原則

### 1. 最簡方案優先
- 先問「這真的需要嗎？」，答案是否就不寫
- 能用 10 行解決的，不寫 100 行
- 能用靜態檔案解決的，不架伺服器
- 能用 CSS 解決的，不寫 JavaScript

### 2. 不增加功能
- 只做需求裡明確要求的事
- 不預測「未來可能需要」而預先建立
- 不因為「順便」就加功能

### 3. 不建立不必要的抽象層
- 直接操作 DOM，不封裝 framework
- 直接寫 inline style 或簡單 class，不建立 design system
- 直接用變數，不建立 class hierarchy
- 重複兩次以上才考慮抽象，一次不抽象

### 4. 每項工作都要有可驗證標準
- 每個任務完成前，先說明「如何驗證它完成了」
- 驗證方式要具體（打開瀏覽器看到 X、點擊後出現 Y、console 無 error）
- 完成後主動執行驗證步驟

---

## 閱讀 requirements.md 的方式

啟用此 skill 後，閱讀 `requirements.md` 時：

1. 列出所有明確要求（忽略模糊描述）
2. 找出最小實作範圍（MVP）
3. 標注哪些是「Nice to have」（不做）
4. 每項需求對應一個可驗證標準

---

## 閱讀 Steering 的方式

啟用此 skill 後，結合 `.kiro/steering/project-rules.md`：

1. 確認技術限制（純 HTML/CSS/JS、docs/ 目錄、無框架）
2. 每次實作前確認不違反任何規則
3. 如需求與 Steering 衝突，以 Steering 為準，並告知使用者

---

## 實作檢查清單

每次寫程式前自問：

- [ ] 這是需求明確要求的嗎？
- [ ] 有更簡單的方式嗎？
- [ ] 我是否在建立不必要的抽象？
- [ ] 完成標準是什麼？如何驗證？

---

## 適用範圍

此 skill 適用於本專案所有開發工作，與 `project-rules.md` steering 並行生效。
