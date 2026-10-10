# LexFlow V0.3 — 司法特考 114 年民法概要 25 題候審核驗

**性質：Draft PR #1 的開發候審程序；不合併、不中斷 V0.2，也不開放計分。**

## 官方文件（真實來源）

- 114 年司法特考考畢試題查詢：<https://wwwq.moex.gov.tw/exam/wFrmExamQandASearch.aspx?e=114120&y=2025>
- 四等法院書記官、執達員、執行員共用之「民法概要」，試題代號 2201。
- 試卷 Q：<https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?c=201&code=114120&q=1&s=0405&t=Q>
- 公布答案 S：<https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?c=201&code=114120&q=1&s=0405&t=S>
- 考試全科目答案總表 A：<https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?t=A&code=114120>

Q 原卷 4 頁：前半申論 2 題，後半 **25 道單選題，每題 2 分**。S 原答案 PDF 為 1 頁、公開的第 1～25 題答案表。

## 來源識別與完整性

與 2026-10-08 GitHub Actions 原始 PDF 抽樣取得結果一致：

| 檔案 | 已核對 SHA-256 |
|---|---|
| Q | `f57cbcd55d4dc1e7fa9c0b0c8e6bc0ef264e17d7573531aa513eb093fe41fc89` |
| S | `18e2b4e83dece0763568b5daa59000fb78a14e8def9eb7558672416b5f923ce7` |

只接受完整的官方 URL 身分 `(exam=114120, c=201, q=1, s=0405, t=Q/S)`。如官網改動 PDF 內容使 SHA 不同，即 **fail-closed**，需要重新檢查來源，不會沿用舊答案或直接發布。

## 官方 S 答案表逐題索引（尚待確認最終更正狀態）

- 第 1–10 題：`A B A A D D B A C A`
- 第 11–20 題：`C B D D B B D D C C`
- 第 21–25 題：`B B A B C`

這些字母從上述官方 S 答案 PDF 原表逐格核對後轉錄，並以原始 PDF 雜湊版本作為資料連結。**已核對 S 公布表的字母，不等於已核實沒有後續更正**：個別 `M`、整份答案總表 A 及官網更正公告仍必須另行交叉核對。

## 必須保留的品質隔離

自動產生之每個題目候審項目都必須設置：

- `question_text_verified=false`
- `options_verified=false`
- `later_correction_checked=false`
- `legal_explanation_verified=false`
- `eligible_for_scoring=false`
- `publication_allowed=false`, `scoring_enabled=false`

**此階段只建立候審對照／原文擷取片段，不能上線 25 道「完整選擇題」或「正確詳解」。** 內部抽取的原文仍應對照 PDF 頁面，核對否定詞、各個數字及 A–D 四個選項。

## 修正 32 筆錯誤類科標籤

原本解析器只辨識含「類科」的考試群組，如 `司法五等考試_庭務員類科`。官方後續有 `調查三等考試_調查工作組(選試英文)`，不含「類科」，因此原 parser 未切換群組，使得部分試卷沿用庭務員類科標籤。本次改採考試等別標頭辨識 (`xxx等考試_yyy`) 並增加跨群組回歸測試。

這是 **來源欄位修復**，不是猜測科目；若來源標籤與試卷 PDF 頁首不一致，仍應標記待查證，不可強制補入。

## GitHub CI 門檻

1. 先執行 `test_moex_index.py`、`test_moex_fallback.py`、`test_moex_document_qa.py`、`test_moex_civil_mcq.py`；若任何一項失敗即停止。
2. 抓取真實 114 年官方 HTML 與限定數量 Q/S/M/A 官方 PDF，寫入 QA artifact。
3. 重新抓取同一份經雜湊釘選的民法 Q/S，寫入 25 題候審 artifact；PDF 異動立即失敗，不以模型猜測填補。
4. 不得修改正式 `main`、`quiz.js`、`data/moex_official_index.json`，不得觸碰使用者備份。
5. 正式計分題庫需另通過 25 道完整題文與全部選項、最終更正答案、法條和詳解的核對。

## 驗收結果（待 GitHub Runner 實測後填寫）

- [ ] 類科上下文切換後，庭務員類科沒有不合理繼承。
- [ ] 4 組 Python 單元測試均加入必要 CI 且通過。
- [ ] 官方 HTML、抽樣 Q/S/M/A PDF 在 Runner 可讀取。
- [ ] 114 年 2201 民法 Q/S SHA 完全吻合；生成 25 條非計分候審紀錄。
- [ ] S 答案對照與最終更正已核對（此階段不宣稱完成）。
- [ ] 25 題題文、選項及逐項法律詳解已核對（此階段不宣稱完成）。

