# LexFlow V0.3｜通用題幹、選項及公布答案對照（候審）

狀態：**開發分支 Draft PR #1，尚未合併正式 `main`。所有候審題目均不得計分。**

## 為何這是通用引擎，而非「另一份民法專用程式」

輸入仍沿用 `lexflow.moex.index.v1` 的官方候審連結索引。`moex_batch_engine.py` 負責來源、身分、下載與單份失敗隔離；新增 `moex_question_pipeline.py` 僅負責**已下載之 PDF 的文字候審解析**，不含年度、科目、題目代碼或民法答案常數。不同試卷共用同一條路徑。

這一輪修改**沿用前一個 GitHub `universal-batch-smoke` 的 7 份跨科 PDF 下載**，並在同一批次完成文字解析，不另開重複下載的 CI 工作，避免增加不必要的對考選部連線。

## 題幹與選項的條件

1. 從試卷 `Q` 官方 PDF 抽取文字。若有「乙、測驗題」段落，避免將前段申論題混作選擇題。
2. 找出從第 1 題開始、連續且**唯一**的題號序列，並核對 PDF 內明示的「共 N 題」。找不到、重複或不完整，即在輸出標示欠缺證據。
3. 辨識官方 PDF 中 `   ` 的 A～D 位置。必須各出現一次且依序，才產出 4 個**原樣未核對選項片段**；否則隔離該題。
4. 若選項中混入 `代號：`、`頁次：` 等跨頁資訊，必須留待對照 PDF 原卷，不能直接作為可閱讀且正確的題目。
5. PDF 是掃描影像、文字順序錯亂、題目太長等情況，進入人工審查，不自動 OCR、不自行補字。

## 公布標準答案 `S` 的處理

- **不使用 AI 推算正確選項**。只有官方 S PDF 內題號與 A／B／C／D 存在可重現且明確的逐題配對（例如題號列＋相鄰答案列），數量完整、不衝突，才產出 `published_standard_candidate`。
- PDF 表格若被文字擷取器打亂，例如先輸出一批題號、下一行才輸出一批答案，**不憑字母順序猜配對**；保存 `answer_table_layout_ambiguous_NEEDS_REVIEW` 而不產生答案鍵值。
- `Q`／`S` 必須有相同的官方文件識別，否則跳過自動配對。其他官方 CSV URL 無法證明配對時，只讀試卷，不對齊答案。
- 更正答案 `M` 保持獨立：即使其中顯示新字母、全題送分或特殊給分，也只標示「更正待人工核對」，**不覆蓋原 S 字母**。整份答案總表 `A` 仍不作為單科的答案來源。
- 只有公布標準答案候審值，**不表示最終答案**；目前沒有資格啟用正式計分。法條、實務見解與逐選項詳解需另行查證。

## 每份題目輸出的不可跨越欄位

- `question_text_verified=false`、`options_verified=false`
- `final_answer_verified=false`、`correction_applied=false`
- `legal_explanation_verified=false`、`eligible_for_scoring=false`
- 整體 `publication_allowed=false`、`scoring_enabled=false`

若解析器或 PDF 下載失敗，該份試卷獨立隔離；原有候審索引與瀏覽器 V0.2 作答紀錄不變。所有輸出僅存 GitHub Actions 暫存的 `moex-cross-field-UNVERIFIED-batch-review`，不更新 `quiz.js`、`data.js` 或公開正式題庫。

## 不增加下載的驗收方式

工作流程更新後，PR 上原有 `universal-batch-smoke` 會用同一批官方 Q／S／M PDF 測試以下命令：

```sh
python scripts/moex_batch_engine.py --live-exam 114120 \
  --max-papers 3 --max-documents 9 \
  --download-documents --require-all \
  --extract-questions --min-choice-candidates-per-paper 3 \
  --output /tmp/lexflow-universal-batch-UNVERIFIED.json
```

* 這個測試只證明可以產生**候審**題幹／選項片段；不是逐字核對、正式答案或自動計分測試。
* CSV 與備援來源維持獨立，暫不擴大官方站點爬取範圍。
* 同時執行原有 70 項 Python 單元測試，加上 20 項本模組針對題文、答案表與安全的回歸測試。只有 CI 真正成功後才能宣稱最新版通過跨科真實來源驗收。

## 尚待工作

逐題**視覺比對 PDF**、答案表多種版型的座標讀取、官方最終更正及特殊給分核驗、法源詳解、不同考試年度完整批次驗證、掃描 PDF 的明確 OCR 工作流程及正式題庫發布，都仍是後續工作。尤其純 PDF 文字抽取無法保證圖表、數學式或有特殊排版的題目正確，應隔離人工核對。
