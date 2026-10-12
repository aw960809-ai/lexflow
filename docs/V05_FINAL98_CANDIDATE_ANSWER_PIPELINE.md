# LexFlow Final98 V5｜原始公布答案與更正文件候審配對（禁止正式計分）

**狀態：Draft PR #1 程式碼。不是正式題庫發行。** 本工具只在手機／本機讀取既有 V4 SHA-256 已核對的 301 個 S/M 官方 PDF 快取；沒有網路下載，不寫入主系統，不動 `lexflow-data-v02`、`lexflow-v03-practice-lab-v1`、`lexflow-final98-shadow-practice-v1` 等紀錄鍵，也不把候審 PDF、題文、答案或私人紀錄提交到 GitHub。

## 基礎證據

- 449 份試卷、9,399 題，其中選擇題 8,290 題、申論題 1,109 題。
- 246 份含選擇題試卷有官方標準答案來源關聯；其中 50 份（原狀態 `MISSING_S`）在 V4 已取得有匹配 SHA-256 的 S PDF。`MISSING_S` 僅代表上游候審分類，不能當成官方沒有答案。
- 301 筆官方 S/M 文件 SHA-256 符合 V4 報告；**指紋吻合不等於 PDF 格子、最終更正或合法給分均已驗證。**
- 8 份共用原卷含跨類科的 17 筆來源關聯，不得只按 Q 檔去重後直接套某類科的答案或更正。
- 2,293 筆原始風險標記原樣保留；20 題五選項題的部分給分規則未自動批准。

## V5 真正執行的工作

1. 比對 V4 ZIP 與 449 分片 ZIP 的來源 SHA-256、題目 ID、題型、數量、`publication_allowed:false` 與 `scoring_enabled:false`。
2. 只讀取 `~/LexFlow_Final98_V4_SourceCache` 的檔案，逐份核對下載 URL 的 metadata、PDF SHA-256 及來源身分；無法驗證則隔離。
3. 使用 `pypdf` 解析明確標示「題號／答案」的 PDF 座標表格。對所有題號要求連續、對齊、不重複、無缺格，另比對可獨立辨識的文字表格。位移、內部缺格、重複頁面或衝突全部不建立候審答案。
4. S（公布答案）與 M（更正文件）完全分離；更正註記、`#`、複數正解及五選項特殊規則均標記待審，**不把 M 的字母直接替換 S，也不把任何字母變成正式給分規則**。
5. 按每一份原卷的完整身分（年度、考試代碼、類科、科目、節次）核對 S/M；不同類科的來源個別保留，不融合成單一答案表。
6. 產生私人報告 ZIP，內含逐題候審答案欄位、S/M 文件解析狀態、風險原因及整卷缺口統計。產物只能用於 V6 後續核驗，不能上傳 GitHub 作正式題庫。

## 執行與測試

```sh
python -m pip install 'pypdf==5.9.0'
python -m unittest discover -s tests -p 'test_final98_answer_candidate_v5.py' -v
python scripts/final98_answer_candidate_v5.py \
    --v4 ~/storage/downloads/LexFlow_Final98_V4_AutoQA_20261012_135713.zip \
    --shards ~/storage/downloads/LexFlow_449_Shards_STAGING_20261012_104030.zip \
    --cache ~/LexFlow_Final98_V4_SourceCache
```

## 說明

- `v5_question_candidates_NOT_FINAL.csv` 包含**未核准的 S 候審字母、獨立 M 格子候審字母與備註選項**。它們不等於最終標準答案，更不可用於正式計分。
- `v5_document_parse_status.json` 的 `COMPLETE_CANDIDATE_NOT_FINAL` 是「這份 PDF 的候審格子解析完整」，而非法律正確性或最終更正已確認。
- 符合一致的 PDF 雜湊但缺文字層或有不明格位時，會標記 `REQUIRES_REVIEW`，不以 OCR 猜測填補；不要求使用者人工逐題操作。
- GitHub CI 只運行**合成測試 PDF**，且不使用本地私有報告；只有使用者手機上的離線腳本才讀取真實 S/M 快取。
- 正式發布前仍需完成官方最新更正、特殊給分、題文／選項原卷對讀，以及最終部署端對端驗收。
