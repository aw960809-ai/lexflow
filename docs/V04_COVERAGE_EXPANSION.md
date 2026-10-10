# LexFlow V0.4｜跨年度整卷取樣與可比較品質報告

## 本次進行的是什麼

本增量**不修改**現有官方 CSV 分類器、PDF 下載器、選擇題／申論題解析器、答案表位置核對器，也不新增題庫或對原題做正式計分。僅增加 `scripts/moex_coverage_campaign.py`，以現有 `moex_review_series.py` 的**最多 3 批／批次最多 8 個 PDF** 規則，安全管理數個獨立年度 cohort，最後把它們的已驗證來源與候審品質結果合成可比較的 JSON 和 CSV。

- 每個 cohort 的原卷 ID、官方考試名稱、年度、類科、科目、題型及 Q/S/M 連結均取自官方目錄；保留整份試卷，不將題號拆成新卷。
- 來源以同一份原始 CSV SHA-256 鎖定。每個 cohort 內的完成紀錄仍由既有引擎維持 create-only；停止後再次執行只補做未完成批次，不覆寫原始報告或私人作答。
- `prepare` 只讀完整官方目錄，不連網；`run-one` 才能透過 **顯式** `--download-documents` 每次限量試跑一個 cohort；`summarize` 僅離線讀取本機候審來源及經指紋驗證的公開 PDF 快取。
- 所有報告都保留 `scoring_enabled=false`、`publication_allowed=false`，候審答案不自動成為正式題庫。

## 2026-10-09 的真實官方 CSV：離線取樣（尚未下載新 PDF）

| 年度 | 已規劃完整試卷 | 官方 Q/S/M 來源文件連結 |
|---|---:|---:|
| 101–103 | 9 | 16 |
| 104–106 | 9 | 15 |
| 107–109 | 9 | 15 |
| 110–112 | 9 | 15 |
| 115 | 9 | 16 |
| **合計** | **45** | **77** |

這是五組不重複的**候審來源規劃**，累積涵蓋 13 個年度；之前已完成 113、114 年九卷試跑，所以本次沒有重複安排那兩年。總共涵蓋多個考試代碼和官方的測驗／申論／混合形式；其中 **1 份「跨領域涉法候選」仍須人工確定是否納入法律題庫**。不能將 45 份全稱為已核准的法律試卷。官方完整科目名稱不做更動。

檢查腳本刻意產生未下載狀態的比較報告：初始 `source_Q_fulltext_SHA_matched=0`、所有解析候選數為 0；這不是下載失敗，而是尚未執行 `run-one`。通過官方 PDF 的來源 SHA 檢查後才增加相應計數。**不可虛構完整題數、全文完成率、最終答案或特殊給分已審查。**

## 執行（Termux；必須有 V0.4 既有 GitHub Draft PR 原始程式）

```bash
# 1. 無網路目錄規劃；在既有公開來源工作目錄下新增五個小 cohort
python scripts/moex_coverage_campaign.py prepare \
  --catalog /path/to/ExamQandA_Csv.csv \
  --output-dir "$HOME/lexflow-v04-catalog-review" \
  --year-groups '101-103;104-106;107-109;110-112;115'

# 2. 僅明確執行一個 cohort 的首批：每次至多 8 個官方文件嘗試
python scripts/moex_coverage_campaign.py run-one \
  --catalog /path/to/ExamQandA_Csv.csv \
  --campaign "$HOME/lexflow-v04-catalog-review/campaigns/campaign-....json" \
  --cohort-index 2 --max-batches 1 --download-documents

# 3. 任何時候都可離線產生五組可比較報告；新資料出現後報告採新檔名
python scripts/moex_coverage_campaign.py summarize \
  --catalog /path/to/ExamQandA_Csv.csv \
  --campaign "$HOME/lexflow-v04-catalog-review/campaigns/campaign-....json"
```

`--cohort-index 2` 是本次最初的**小樣本實際試跑**（104–106 年三卷、三種題型）；其餘 cohort 必須再獨立明確執行，不會自動連續下載所有 77 個文件。`--offline-only` 可在已有公開 PDF 快取時使用，但缺少的文件會留下待審紀錄，不能冒充已下載。

## 品質統計的正確意義

- **規劃完整試卷數**：僅有官方目錄與來源身分索引，不代表已下載。
- **Q 全文 SHA 相符試卷數**：原始官方 Q 試卷已保存擷取文字、其指紋與來源候審報告一致，但題文可能缺字或缺圖。
- **四選項候選／申論題號候選**：規則擷取的卷內索引，尚未確認卷內完整題數，原試卷保持一份。
- **位置式答案候選、含特殊給分涵蓋、衝突**：只有同源且 SHA 相符的官方答案快取可計入，**不能**等同為已人工核准的標準答案。
- **標題法律相關性**：分類只是官方名稱層的發現提示。像「外國文（英文兼試移民專業英文）」這種跨領域候選，不應未審查就宣稱為法律試題。
- `official_total_question_count_confirmed=false`、`fulltext_completeness_rate=null` 持續保留，直到有獨立的逐頁／逐題品質審查。

## 安全上限及下一門檻

腳本對單一規劃最多 **8 cohorts、每組 12 份、最多 96 份完整試卷**，分別使用既有的三批／每批八文件上限；不會因 CLI 預設值意外同時向考選部請求數十份 PDF。請先實際試跑 104–106 年這一組的第一批，將產出的**公開來源候審** JSON／CSV 分享供分析。若來源格式變動或超時，保留異常待審、不可降低 SHA 或網址檢查來聲稱成功。

正式 `main`、正式 GitHub Pages、任何 `localStorage`／使用者作答、自建試卷均不在修改範圍。只允許往既有 **Draft PR #1 開發分支** 非強制推送原始程式、測試及本說明；公開倉庫不放大量原始 PDF、全文或私人 JSON 備份。
