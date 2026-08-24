---
inclusion: always
---

# 專案規則（Project Rules）

## 技術限制

- 只使用 **純 HTML、CSS、JavaScript**，不引入任何框架（React、Vue、Angular 等）
- 不使用 Node.js、Vite、Webpack 或任何建置工具
- 不呼叫任何外部 API（無 fetch 到第三方服務）
- 所有依賴皆透過 CDN `<script>` 或直接內嵌，不使用 `npm install`

## 檔案結構

- 所有網站檔案（HTML、CSS、JS、圖片）一律放在 `docs/` 資料夾
- 進入點為 `docs/index.html`
- CSS 放在 `docs/css/`，JavaScript 放在 `docs/js/`，圖片放在 `docs/assets/`

## 資料與語言

- 所有模擬資料（假資料）直接寫在 JavaScript 變數或 JSON 檔案中，不需後端
- 介面語言使用**繁體中文**
- 版面必須支援**響應式設計**（RWD），適配桌機與手機

## 發布方式

- 透過 **GitHub Pages** 發布，來源設定為 `main` 分支的 `docs/` 資料夾
- 所有連結使用相對路徑，確保 GitHub Pages 環境下可正常運作

## 開發原則

- 不要在未被要求時主動建立網站程式碼
- 每次只做被要求的部分，逐步交付
