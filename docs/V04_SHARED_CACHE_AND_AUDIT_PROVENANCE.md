# LexFlow V0.4｜共用 PDF 快取與跨批次品質稽核整合修正

## 根因與修正範圍

`moex_review_series.execute()` 已將公開官方 Q/S/M PDF 保存於 `official-review/official_pdf_cache/`，但舊版 `moex_quality_overlay.make_overlay_from_disk()` 只會搜尋 `session-reviews/<session-id>/official_pdf_cache/`。因此 9 份試卷的報告雖記錄 15 個 PDF、135 個舊候審答案候選，統一品質稽核的「位置式答案配對」卻為 0；這不等於原始答案缺漏或下載失敗。

此次**只修改既有調度／品質解析呼叫的快取指向與版本辨識**，並未建立新下載器、題庫或 PDF 解析器：

- `moex_catalog_bridge.run_plan()` 把已使用的同一個 `cache_root` 明確傳給 `make_overlay_from_disk()`；原 Q/S/M 來源報告、擷取文字與共用 PDF 位元組均不覆寫。
- `moex_quality_overlay._read_cache_pdf()` 新增可選 `cache_root`；原有單卷呼叫仍可使用各自的舊目錄。共用快取必須 URL 與 SHA-256 一致、PDF 與中繼資料俱全、且不得透過符號連結；下游 `inspect_corrected_pdf()` 再把 PDF SHA-256 與原候審報告中的**同一 Q/S/M 文件**核對。
- `moex_review_series.audit()` **離線**重新檢查共用快取。若原有「未取得答案 PDF」的品質影本與新「來源 SHA 確認」的影本同時存在，保留兩個獨立檔案，但僅選用**本次依已驗證來源產生的候審版本**；不因多版本而誤報衝突，也不把舊影本冒充新來源核對結果。
- 若 PDF 缺少、損壞、與原始報告 SHA 不符、遭插入符號連結或資料格式不明，**不沿用先前成功影本的答案**，保持隔離並列出 `quality_overlay` 異常原因。
- 原申論卷已存在非空擷取文字、但大題仍 0 筆者，新增 `essay_heading_needs_manual_review`，只標為待審，不猜測題號。原始試卷仍是整份存放。

## 稽核數據應如何解讀

- `original_answer_pairs_unverified`：既有題目解析器從原始來源保存的答案候選；**不是**新的位置式核對數量。
- `positioned_answer_pairs_unverified`：本次使用同源且 SHA 相符的已快取答案 PDF，以位置式表格取得的**單一選項候選**數量。
- `answer_cells_including_special_credit_unverified`：上述單選候選與已辨識的多選特殊給分候選的合計涵蓋（仍須審查）。例如合成 M PDF 在第 20 題為 B/C 特殊給分時，應記錄 **49 個單選候選、1 個特殊給分、共 50 題覆蓋**，不可變成單選第 20 題。
- `quality_preview_versions_for_source`：同一原始報告下的候審版本數量；舊檔不會被刪除。
- `essay_papers_with_headings_needing_review`：全文 SHA 相符但無法辨認大題編號的申論卷數。此項不是已解析出完整大題的比例。
- `official_total_question_count_confirmed=false`、`fulltext_completeness_rate=null`：官方總題數與逐字核對未完成，**不可捏造完成率**。

所有候審輸出維持 `publication_allowed=false`、`scoring_enabled=false`、`human_answers_verified=false`，不接入正式計分，不抓取或修改私人作答。

## 既有九卷的驗收方式（不用重新下載）

此修正應以手機現有 `series-b0e2c9b137f82869364f` 來源批次，在包含公開 PDF 快取的 Termux 環境執行 `audit`。9 份 PDF 題文來源 SHA 已先前核驗，這輪只重新生成新的 **create-only** 品質候審影本和稽核 JSON。

已知來源檢查樣本：
- `moex-bca755558759179ef6936bc3`，114 年法學大意：新版應能從同源 M PDF 產生 49 個單選答案候選及第 20 題 B/C 特殊給分，共 50 題候審涵蓋。
- `moex-d58aaf8942ed47cac8a039fa`，114 年基礎能力測驗：新版應能從同源 S PDF 產生 30 個位置式答案候選，且與既有候審答案無衝突。

上面是**尚待 Termux 以實際 PDF 重新測試的驗收標準**，不是本機已完成的真實官方來源驗證。合成 PDF 模擬已通過，但不能取代官方 PDF 的逐題視覺核對。若任一標準未達到，腳本留下新 QA 並停止推送，沒有改變正式 `main` 或試題內容。

## 開發安全邊界

限定 Draft PR #1 開發分支 `feat/v03-moex-official-index-20261008`。不合併 `main`、不強制推送、不覆寫既有 PDF／報告／品質候審檔，不向公開倉庫提交私人作答或真實試題全文。新增測試包含共享 PDF 身分與 SHA 核對、30 題 S、50 題 M、更正備註、舊新品質檔版本、缺格／損毀／符號連結、不變的單卷路徑及零申論題號的待審標記。
