# LexFlow V0.3｜考選部候審自動載入橋接（隔離實驗）

## 交付範圍與現況

本變更只位於既有 **Draft PR #1**；未經使用者核准不得合併 `main`，也不得修改 V0.2 的 `lexflow-data-v02`。候審資料不是真正核驗完成的國考題庫，且無論來源檔案是否存在，**全部都不計分**。

- GitHub 上的 `moex_batch_engine.py` 以同一套流程取得少量官方 PDF 試卷及答案文件，記錄 Q／S／M 出處、 SHA256、題號、四選項與更正警示。這只是來源文件與文字候審。
- `moex_release_gate.py` 檢查並**確認未達人工品質門檻**；`moex_candidate_feed.py` 要求該報告與原始批次完全一致，拒絕不可信來源、重複題號、錯誤 Q／S 配對、未完成結構與所有偽造的計分許可。
- 成功後產生 `moex_review_candidate.json`，其原始 SHA256 可由瀏覽器核對。這份檔案須經 **人工審閱 Draft PR / 資料候審 PR** 才能出現在對外公開的 `main`。
- 只有該檔已經被審查並實際存在於同一個網站時，`candidate-feed.mjs` 才會由 **同來源**自動讀取；未上線、壞 JSON、雜湊不符或來源異常，都不顯示為官方候審題庫，不會假稱不存在歷屆試題。
- 主系統的「題庫」會顯示候審試卷供選擇；學習室只在使用者**點擊開始**某一份試卷後，才把單份未核驗快照存到 `lexflow-v03-practice-lab-v1`，以防遠端更新破壞進行中的練習。既有手動匯入的試卷優先，不會被遠端同 ID 覆寫。
- 不會抓取、上傳或同步私人作答。`app.js` 讀取 V0.3 學習室資料僅為唯讀的題庫標題；V0.2 紀錄與自編法條測驗不會改寫。

## GitHub 流程與必須承認的限制

目前 Draft PR 的 GitHub CI 可以測試真正的官方個別頁面、限量 PDF 及候審 JSON 生成。**每日定時任務只有在 workflow 合併至 `main` 後才會啟用**。設定的 cron `23 23 * * *` 是 UTC，大約為臺灣早上 07:23；GitHub 排程不保證準時。

正式排程設計：嘗試考選部 CSV → 失敗改用已審核的個別考試頁面 → 小批次官方 Q/S/M PDF → 安全檢測 → 產出候審資料與 Draft 資料 PR。**不自動合併、不自動把候審答案變成計分題**。若來源下載失敗或發布閘門拒絕，保留最後有效檔案，最新結果僅以工作產物呈現。

GitHub Actions 的「允許 GitHub Actions 建立 Pull Request」權限與 `GITHUB_TOKEN` 寫入權限，尚須在實際預設分支跑一次才算完成驗證。若權限不足，不可改用強制推送或關閉來源驗證來掩蓋失敗。工作產物保留期間有限，也不能代替長期備份。

**與「全自動、隨時、免費更新國考題庫」仍有距離：**目前只測了代表性三份試卷；未擴展至跨年度全量、自動更正最終答案、逐題法源詳解。未經專人審查的更新不會直接顯示到公開正式網站，這是刻意的安全設計。

## 使用者體驗（測試版）

1. 打開「統一題庫」，官方候審試卷只在這個 GitHub 網站有通過審查的靜態候審檔時自動出現，並顯示「非正式分數」。
2. 點選某份「開始候審自測」進入學習室、選擇開始，系統才保留那份試卷的本機副本；不用手動尋找 JSON。
3. 若沒有新候審資料，仍可使用原有自編題、申論題與手動 JSON 匯入；沒有任何功能需要持續在線才能保存已開始的練習。
4. 使用者可匯出 V0.2 及 V0.3 各自的備份；兩者儲存區不會自動合併。

## 執行與測試

```bash
python3 -m unittest discover -s tests -p 'test_moex_*.py'
node --test tests/practice-core.test.mjs tests/catalog-core.test.mjs tests/candidate-feed.test.mjs
```

人工產出 staging feed（不經人工 PR 合併不會更新網站）：

```bash
python3 scripts/moex_release_gate.py --input review.json --output readiness.json
python3 scripts/moex_candidate_feed.py --input review.json --readiness readiness.json --output data/moex_review_candidate.json
```

## 明確的下一道發布門檻

使用者在 Android 上核對 HTTPS 網站的頁面、長期儲存、PWA 快取更新及跨版本備份；本人確認之後才能合併 V0.3 PR。即便合併，官方候審題仍只供**未核驗的自測**，正式可計分國考題庫必須另經題幹／選項逐題視覺核對、最終答案更正／特殊給分、法源有效日及人工審查。
