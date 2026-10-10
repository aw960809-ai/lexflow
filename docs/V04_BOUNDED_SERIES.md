# LexFlow V0.4｜整卷分流、限量連續批次與品質稽核

## 位置：沿用既有引擎，不另開平行題庫

這項修改只增加 `moex_review_series.py` **調度程式**，而非新的下載器、OCR、題目解析或計分引擎。它呼叫既有的 `moex_catalog_bridge.make_plan` 與 `run_plan`，下游仍由 V0.3 `moex_batch_engine` 執行原始 Q／S／M 身分核驗、下載及保守解析，再由既有 `moex_quality_overlay` 進行候審品質檢查。保留整份原始試卷身分及官方完整科目名稱；卷內題號只是索引，不拆成新原卷。

**正式 `main`、GitHub Pages 題庫、自建題及私人作答均不在這次修改範圍。** 本次不可據此宣稱已完成全量 67,026 份 PDF 或 20,394 份法律候選卷的下載。

## 已有及新增能力

1. 從原始官方 CSV、增強 CSV 或現有 SQLite 進行離線選卷；依官方「測驗題／申論題／混合題／實地考試」分流。測驗和混合卷一起下載 Q + 官方可配對的 S／M；申論先取得 Q 和可讀題文，擬答另待審核。
2. `prepare` 只產生最多 **3 批、每批 1–4 份完整試卷、每批至多 8 個官方 PDF 文件**的不可覆寫規劃。三批的文件預算總上限是 24 個，無網路請求。預設跨年度覆蓋抽樣為三批、每批三卷。
3. `execute` 必須明確指定 `--download-documents`（真實官方連線）或 `--offline-only`（只讀既有公開 PDF 快取），不能默默啟動爬取或永無止境執行。每次最多三批；原批次產生不可覆寫的完成紀錄，重啟會跳過已完成批次。
4. 若 PDF 失敗／離線快取不足，不寫完成檢查點、不重寫原始報告；稍後可明確重新執行。其他正常卷保持已下載來源及報告不變。
5. 同一官方網址、經 SHA-256 比對的**公開** PDF 快取可跨批次重用；但由於不同版本的 CSV SHA 會變動，候審報告分開放在 `session-reviews/<session-id>/`，不能把不同來源版本的核對報告視作相同。
6. `audit` 依已儲存的來源報告及擷取文字重新核對指紋，統計「已有候審報告」、「PDF 文件數」、「可核對 SHA 的擷取全文」、「選擇題四選項候選」、「申論題大題候選」、「答案對位候選」、「特殊給分候選」與各種隔離原因。**官方實際總題數若未核驗，不計算全文完成率，也不給分。**

所有來源及後續 QA 報告均保持 `publication_allowed:false`、`scoring_enabled:false`、`human_answers_verified:false`。這是本機／Draft PR 的候審證據，不能自動提交到對外的正式題庫。

## 實際執行（Python 3.10+，pypdf 5.9.0）

```sh
# A. 先離線規劃 9 卷：113、114 年、測驗／申論／混合三種（不下載）
python scripts/moex_review_series.py prepare \
  --catalog /path/to/ExamQandA_Csv.csv \
  --output-dir /path/to/lexflow-v04-review \
  --years 113,114 --strategy coverage --batches 3 \
  --papers-per-batch 3 --documents-per-batch 8

# B. 使用上一步輸出的 session_dir，**明確啟用下載**，至多 24 個 PDF 文件嘗試
python scripts/moex_review_series.py execute \
  --session-dir /path/to/lexflow-v04-review/sessions/series-... \
  --catalog /path/to/ExamQandA_Csv.csv \
  --download-documents --max-batches 3

# C. 統一品質報告（完全不連網、不變更原卷）
python scripts/moex_review_series.py audit \
  --session-dir /path/to/lexflow-v04-review/sessions/series-...
```

連續盤點 101～115 年的其他試卷時，另以 `--strategy sequential --start-row <上次的 catalog_cursor_next_row>` **新開一個明確的限量規劃**。抽樣策略 `coverage` 為跨年跨題型覆蓋，不保證序號連續，因此不產生可安全接續的全量游標，不能誤用最大來源列號跳過資料。

## 嚴格的驗收界線

本更新使用使用者提供的 67,026 列官方 CSV **離線**實跑，選出 9 卷（113、114 年，跨 4 組考試代碼，測驗／申論／混合各 3 卷），成功產生三批來源規劃；所有 PDF 下載仍需在 Termux 網路環境真正執行。CI 的新增測試不會向考選部發送 24 個請求，而是檢查失敗保留、續作、來源指紋、題型分流、候審統計、不合法資料隔離等。

手機實際下載成功，也只能稱為「來源 PDF 候審與文字候選」，不是每道題目的逐字核對、最終更正答案核准或正式分數。不得合併 `main`、強推、清除既有作答或提交公開原始 PDF／私人成績。
