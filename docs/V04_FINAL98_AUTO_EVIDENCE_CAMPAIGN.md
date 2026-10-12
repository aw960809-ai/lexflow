# LexFlow Final98 V4｜全量來源證據自動盤點與再確認（Draft，禁止正式計分）

**狀態：程式碼開發、非正式發布。** 保留 GitHub PR #1 為 Draft，不得因 CI 綠燈或 PDF SHA-256 一致就將 9,399 題投入正式計分題庫。

## 解決的核心缺口

- 449 份整卷、9,399 題原先已有機器證據；本階段不重新建題、不修改題文，不觸碰 `lexflow-data-v02`、`lexflow-v03-practice-lab-v1` 或 `lexflow-final98-shadow-practice-v1`。
- 246 份含選擇題的試卷中，196 份（6,610 題）列為 `EXISTING_S`，50 份（1,680 題）列為 `MISSING_S`。注意：`MISSING_S` 在舊資料仍可能有官方 URL 和歷史 SHA，不能直接當成「考選部未公布答案」，須重新下載及比對。
- 原始來源包含 17 筆跨類科 `c` 關聯，涉及 8 份原卷。保留同一 Q 的來源身分關係，但**不得跨類科自動套答案或更正**。
- 2,293 筆風險標記（1,841 題）持續保留；另含 34 組共用文章、20 題五選項題。

## V4 新增機器工作

`python3 scripts/final98_source_qa.py --shards path/to/LexFlow_449_Shards_STAGING_*.zip --mode offline`

機器重新核驗分片 SHA、原卷 Q 來源身分、所有題目 ID、題型及選項、共用文章、所有來源 URL、20 種風險代碼、答案檔 S / 更正檔 M 與考試類科關聯；輸出：

- `audit_summary.json`：總量、風險、缺口、跨類科身分、所有安全鎖。
- `paper_gap_matrix.csv`：449 卷完整風險與 S 來源狀態。
- `question_evidence_matrix.csv`：9,399 題逐題 ID、風險類型、題型、科目與原始證據 SHA（**不含題目正文、選項或個人答案**）。
- `official_source_recheck.json`：待重新查核的 301 個來源 URL、來源雜湊與技術驗證結果。

`--mode source-recheck` 則從原先已記錄的考選部官方 S、M 網址，優先重查 `MISSING_S`／`MISSING_M`，再比對 `EXISTING_M`／`EXISTING_S`，使用 HTTPS、網域限制、PDF 魔術位元、檔案尺寸上限和 SHA-256；16 MB 超額、錯誤 HTML、官方封鎖、SHA 不符、轉址均拒絕自動放行。快取僅存於 Termux 私人資料夾，支援再次執行重用，報告不含 PDF 位元組。

預設來源連線每次間隔至少 0.8 秒、每份文件 20 秒逾時、總 15 分鐘時間上限；超過時間或網路錯誤，保留待查，不可默默當通過。

## 清楚區分五種不同的完成

1. **分片結構驗證**：機器處理完成。
2. **官方來源 PDF SHA 比對**：V4 可自動做，仍可能失敗／變更。
3. **題文逐字對照及選項校準**：不能光靠 PDF SHA 證明；風險題依據持續追蹤。
4. **公布答案、適用類科、最新版更正、複數給分／五選項部分給分**：V4 沒有自動核准，也不自行從 S/M 猜出最終答案。
5. **正式網站發布、國考分數、法律詳解**：均不啟用，必須另行實質證據與部署 E2E 才能放行。

## 安全要求

只在既有 Draft PR 加入腳本、單元測試、說明和 CI。CI 僅執行合成資料的測試，選用環境變數 `LEXFLOW_FINAL98_SHARDS` 才可在本機驗 449 份私人來源；不會把任何正式 PDF、題文、分片或私人作答送到公開 GitHub。正式主程式、`main`、PWA 儲存和 GitHub Pages 一律不變。
