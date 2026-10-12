# LexFlow V0.4｜全量考選部目錄橋接（非正式題庫）

## 宗旨

本次直接承接考選部 CSV 既有 67,026 筆整卷目錄資料，不另建立科目專用工作台，也不更動已通過 Android 驗收的 V0.3。每一筆保留 **完整考試名稱、年度、等別、類科、官方科目全名、官方試題型態及同卷試題／答案來源**；任何「題目片段」僅為該卷內部待審索引。

## 實際建置

1. 直接讀取既有 `official_catalog.sqlite`、`all_exam_papers_enriched.csv` 或官方原始 14 欄 CSV。預設只選先前已標註的「法律相關候選」，也可使用 `--scope all`，未列為候選的資料並不等於沒有法律內容。
2. 用官方 `測驗題／申論題／混合題／實地考試` 欄位路由，不對科目自行改名；「綜合法政知識與英文」永遠保留完整原始名稱。
3. 選擇與混合題同卷取得官方 Q+S 或 Q+M；M 為更正答案來源，**不是已經完成更正套用**。申論題先取得 Q，另外儲存整卷文字及卷內題幹候選段落，不捏造官方標準答案。
4. PDF 取得與可讀性驗證**重用 V0.3 原本的 `moex_batch_engine.py`、`moex_document_qa.py`、`moex_question_pipeline.py`**，不是另一套下載器。非官方 URL、Q/S/M 身分不符、超出下載上限都會停止或隔離。
5. 保留原卷 PDF（以官方網址雜湊命名的唯讀來源快取）及可擷取的試卷全文；來源改變或檔案被竄改，拒絕誤用。
6. 預設只離線產生可重現的規劃；只有明確執行 `review` 才會連線。每次最多 **12 份原卷、24 個 PDF 下載嘗試**，預設每次僅 3 份，下載間隔至少 0.5 秒；不提供會在第一次執行就嘗試 20,394 張試卷的指令。
7. 已存在的報告不覆寫、不重新推送；每張試卷均維持 `publication_allowed:false`、`scoring_enabled:false`。不讀取使用者 `localStorage`、作答記錄及備份。

## 三種實際狀態（不得混稱）

- `planned_review_not_downloaded`：CSV/SQLite 目錄及來源連結通過基礎驗證，**沒有**下載 PDF。
- `downloaded_source_still_requires_human_review`：來源 PDF 可取得並通過 V0.3 結構檢查；全文／卷內片段仍需人工對照 PDF 版面，未確認完整題數與答案。
- `partial_or_isolated_source_needs_review`：來源、擷取或同卷資料不完整，不能當作可用正式題庫。

## 可重現指令（在含 V0.3 `scripts/` 的 checkout 中執行）

```sh
# 範例：來自完整原始資料目錄，跨年度 + 官方三種題型、挑 9 份試卷
python scripts/moex_catalog_bridge.py plan \
  --catalog path/to/official_catalog.sqlite --years 113,114 --limit 9 \
  --output /tmp/lexflow-113-114-plan.json

# 顯式實際下載（需 pypdf==5.9.0，官方可用性取決於當下網路）
python scripts/moex_catalog_bridge.py review \
  --plan /tmp/lexflow-113-114-plan.json \
  --output-dir "$HOME/lexflow-official-pdf-review" \
  --max-papers 3 --max-documents 9

# 批次後續試卷第 4-6 份：不影響第一次報告
python scripts/moex_catalog_bridge.py review \
  --plan /tmp/lexflow-113-114-plan.json \
  --output-dir "$HOME/lexflow-official-pdf-review" \
  --start-at 4 --max-papers 3 --max-documents 9

# 全年度全面盤點採序號游標逐批產生規劃，不發送任何網路請求
python scripts/moex_catalog_bridge.py plan \
  --catalog path/to/official_catalog.sqlite --scope candidates \
  --strategy sequential --start-row 1 --limit 12 \
  --output /tmp/lexflow-catalog-first-12.json
```

CLI 傳入 `--scope all` 才會納入其餘未標記科目。產生完整目錄的進度與各種例外，應記錄至獨立文件，不應把使用者作答紀錄放入公開 GitHub 倉庫。

## 現在尚未完成

本更新已離線讀取全量目錄並製作跨年度 9 卷來源規劃，也通過合成 PDF 與 URL 身分測試；**目前這個執行環境無法直接連線下載考選部真實 PDF**，因此不能宣稱已下載、全文抽取、逐題核對所有原卷。GitHub Draft PR 尚未推送本次新程式；正式 `main` 不可擅自合併。實機／GitHub CI 需在正式執行與提交後分別驗收。
