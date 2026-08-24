# GitHub Pages 發布技能

依據 GitHub 官方文件查核確認。
來源：https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site

---

## 發布方式：從 branch 發布（本專案採用）

### 操作步驟

1. 確認 `main` branch 存在且 `docs/` 資料夾已建立
2. GitHub repo → **Settings → Pages**
3. **Build and deployment → Source** → 選 `Deploy from a branch`
4. **Branch** → 選 `main`
5. **Folder** → 選 `/docs`
6. 點 **Save**

發布後網址：`https://<username>.github.io/<repo>/`

---

## 本專案設定

| 項目 | 值 |
|---|---|
| Branch | `main` |
| Folder | `/docs` |
| 進入點 | `docs/index.html` |
| 路徑規則 | 全部使用相對路徑 |

---

## 每次建立網站檔案前的檢查清單

- [ ] `docs/index.html` 存在（Pages 進入點）
- [ ] `docs/.nojekyll` 存在（空檔案，停用 Jekyll）
- [ ] 所有 CSS / JS src 使用相對路徑，不用 `/` 開頭
- [ ] 無任何 Node.js 建置步驟（純靜態，Pages 直接服務）

建立 `.nojekyll`：
```powershell
New-Item -ItemType File -Force -Path "docs/.nojekyll"
```

---

## 官方文件確認的重要限制

- Public repo 可用 GitHub Free；private repo 需 GitHub Pro 以上
- 刪除 `docs/` 資料夾後會觸發 build error
- 純靜態不需要 GitHub Actions workflow
- Source folder 只能選 `/`（根目錄）或 `/docs`，無其他選項

---

## MCP Fetch 設定（已寫入）

位置：`~/.kiro/settings/mcp.json`

```json
{
  "mcpServers": {
    "fetch": {
      "command": "npx",
      "args": ["-y", "kazuph/mcp-fetch"],
      "disabled": false
    }
  }
}
```

Node.js 環境：v24.18.1 / npx 11.16.0（已確認可用）
