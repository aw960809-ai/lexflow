# LexFlow V0.3 補充規格：考選部個別頁面備援來源

狀態：**候審，未合併、未發布；不能宣稱官方題庫已可自動更新。**

## 已核對的真實來源

- 官方考試頁：https://wwwq.moex.gov.tw/exam/wFrmExamQandASearch.aspx?e=114120&y=2025
- 114 年司法四等（法院書記官等）民法概要 **試卷**：https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?c=201&code=114120&q=1&s=0405&t=Q
- 對應 **測驗式答案 PDF**：https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?c=201&code=114120&q=1&s=0405&t=S

已從正式 PDF 確認此原卷 **申論 2 題／50 分，以及單選 25 題／50 分**。答案連結存在不等於已核對答案 PDF 內容；另應追蹤更正答案（可能存在 `t=M`）。

## 為何增設第二來源

政府開放資料 CSV 連結可用於涵蓋大量試卷，但 2026-10-08 的 Termux 嘗試獲得 `Connection reset by peer`，Chrome 亦卡住；單一正式 PDF 則可開啟。兩個入口連線結果不同，**不代表**程式能自動讀取整個 HTML 頁面，仍需真實來源煙霧測試。

## 資料來源優先順序

1. 保留 CSV 為主要全量索引：成功且通過格式／筆數／來源檢查才更新 `data/moex_official_index.json`。
2. CSV 失敗時，僅從**已核准的** 114 年司法特考 HTML 查詢頁擷取官方文件連結，寫入**獨立的** `data/moex_official_fallback.json`，絕不縮減或覆蓋主索引。
3. HTML 下載失敗、缺乏年度識別、文件連結格式異常、候審筆數太少時 fail-closed，兩份舊索引都不修改。
4. 前端可唯讀合併顯示兩種索引，依原始文件連結去重；**不修改使用者本機作答、備份、計時、測驗答案**。

## 資料可信度

**本輪只驗證官方 HTML 上出現了特定試卷／答案連結，未驗證以下事項：**

- 連結目標是否為完整真實 PDF；
- 原卷的 25 道選擇題是否正確拆題、各選項是否完整；
- 測驗式答案是否為已更正後的最終答案；
- AI 法學詳解、申論批改是否達到專業正確性。

因此本輪不改動 `quiz.js`，不得把官方連結索引變成正式可計分題庫。

## GitHub 安全策略

- 延續 `feat/v03-moex-official-index-20261008` 分支和既有 Draft PR #1。
- 新增 PR 真實官方頁面 smoke test，CI 只有模擬通過不代表來源抓取成功。
- 新增 schedule/手動任務：主 CSV 失敗即以官方個別頁面備援；同步資料需經獨立候審 PR，不可直接合併 main。
- 若既有 `bot/moex-index-review` 候審分支存在，**不 force push、不覆蓋**，新候審資料只保留工作產物待確認。
- GitHub workflow 的 schedule 在檔案合併到 main 前**不會開始執行**。

## 後續驗收

- [x] PDF 官網直連透過手機實測可開啟，官方文件格式與題型已核對。
- [x] 雙來源隔離設計與離線自動測試。
- [ ] GitHub runner 真實下載官方 114120 HTML 成功。
- [ ] 真實 HTML 擷取候審筆數、民法概要 `201 / 0405`、答案 URL 均符合官網。
- [ ] GitHub workflow 報告和來源 URL 逐筆核對。
- [ ] PR #1 經使用者確認合併後，正式網站才會讀取備援索引。
