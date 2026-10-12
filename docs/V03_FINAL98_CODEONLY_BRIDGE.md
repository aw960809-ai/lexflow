# LexFlow Final98：程式碼整合，非正式題庫發布

**狀態：Draft PR #1 的 code-only bridge。未合併 `main`、未發布 449 份候審卷、未啟用官方計分。**

## 範圍

- 原 LexFlow V0.3「題庫」新增 `449 份整卷`，用同一個 LexFlow 介面呈現按法科、題型、年份、風險標記、題幹搜尋的隔離來源。
- 在原「批改／作答」新增 `整卷候審` 檢視頁，唯讀顯示 `lexflow-final98-shadow-practice-v1` 的未完成與已交卷摘要。
- 正式資料 `lexflow-data-v02`、舊版 `lexflow-data-v01`、V0.3 `lexflow-v03-practice-lab-v1` 全部維持原有擁有者與格式，**不遷移、不覆寫、不合併評分**。
- 449 份原始分片、`catalog.json`、SQLite、機器驗證與個人資料均**不提交到公開 GitHub repository**。私有 staging 僅當專案同來源底下已存在 `/_staging_449/` 才會可用；否則顯示未安裝，主系統本身仍可正常運作。
- `staging-native.mjs` 本身沒有依賴私有 staging 的靜態匯入，瀏覽器只在通過來源檢查時懶載入候審練習紀錄驗證器。
- 每次讀取 `catalog.json` 必須同時核對來源 SHA-256、449 份／9,399 題與安全旗標；每份試卷在原隔離練習室還須通過自身的 SHA-256 驗證。
- 不把整卷候審作答計入既有自編題的答對率、AI 批改或正式成績，禁用任何候審官方答案顯示。
- Service Worker 不快取 `/_staging_449/` 內容，且只刪除 LexFlow 自身命名空間的快取，避免其他 GitHub Pages App 受到影響。

## 限制及後續放行條件

1. 此變更僅為程式碼 integration readiness，無法證明全部題目的原卷與官方更正答案均已通過內容審核。
2. 分片 ZIP 中保留的 2,293 筆風險標記及任何內容審核欠缺不能因介面驗收而消除。
3. 必須完成全量內容與官方更正答案品質核驗，以及在最終部署路徑的 Android/桌面端對端測試，才能討論正式題庫發布與計分。
4. 不能將 V0.3 Draft PR 直接標記為 Ready 或合併 `main`；開發分支仍為 Draft。

## 本機測試

```
node --test tests/staging-native.test.mjs
# 如有本地 Final98 既有隔離索引：
LEXFLOW_CATALOG_PATH=/path/to/catalog.json node --test tests/staging-native.test.mjs
```

程式碼提交可在原 Draft PR #1 開發分支以 **fast-forward** 形式進行；需要 Repo 寫入權限，工具不得繞過 GitHub 授權。
