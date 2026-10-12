# LexFlow Final98 V6｜精確類科與混合選擇題來源證據

狀態：**僅限私人候審／GitHub Draft PR #1 的程式碼變更**。絕不發布題文、未核准答案、PDF、私人作答、計分規則或正式題庫。

## 已有且不應重做

V4 核對 301 筆官方 S/M PDF SHA-256 均一致。V5 首輪獲得 7,750/8,290 題 S 候審答案；540 題未獲得安全候審值。所有來源證明都仍屬機器候審，不構成最終答案核准。

V6 在現有三份私人 ZIP 中，對 *相同 code/c/s/q 身分* 的 S 文件單獨定位，成功挽回 **400 題**。共用試卷的其他類科 S/M 文件即使 SHA-256 相同也要保存為不同的來源關聯，不能直接套用。

剩餘 140 題來自兩份 70 題試卷，官方答案 PDF 明文區分 **前 60 題單選（1–60）及後 10 題複選（61–70）**。V6 僅在從手機 **原有 V4 SHA 已核對之私人快取** 以 PDF 座標完整取得 70 題、且聲明題數正確時，才產生 120 個單選與 20 個五選項多選候審值；缺格、斷欄、重複題號、坐標衝突或 PDF 指紋不符一律保留未配對。

## 40 份 M 更正來源

V6 只從現有快取讀 M PDF 的文字備註，並要求更正註記 `#` 的原題號和備註題號相符。辨識三類字面候選：一律給分、數個答案均給分、明文更換答案。所有候選為 **未經法律內容與最新更正時點核准的證據**，獨立顯示，不覆寫原 S 答案。無法解析、備註重複、題號不明、無 `#` 對應，維持疑義。

## Termux 輸入與產出

輸入：原本存在 Download 的 `LexFlow_Final98_V4_AutoQA_*.zip`、`LexFlow_Final98_V5_Candidates_*.zip`、`LexFlow_449_Shards_STAGING_*.zip`，以及 Termux 私有目錄 `~/LexFlow_Final98_V4_SourceCache/` 中已核對的 PDF。

輸出：`LexFlow_Final98_V6_Targeted_日期時間.zip`，包含逐題候審值、保留原 V5 不覆寫欄位、精確類科 S 來源、M 更正備註及異常清單。此 ZIP **不可提交到公開 GitHub**。

GitHub 只允許提交 `scripts/final98_v6_targeted.py`、`tests/test_final98_v6_targeted.py`、此說明及 CI workflow 的一次小型變更。CI 僅使用合成 in-memory PDF 排列測試，不包含私人快取、原卷或個人紀錄。

## 放行鎖

- `publication_allowed = false`
- `official_scoring_enabled = false`
- `production_import_allowed = false`
- `final_answers_verified = false`
- 原本 2,293 筆題文風險標記維持原狀。
- 官方更正發布時點、所有有效更正是否完整、個別題文與選項法律內容核對、五選項實際配分方法，仍需另外核准才能發布及正式計分。
