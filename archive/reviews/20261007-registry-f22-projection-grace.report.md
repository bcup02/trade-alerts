# Perplexity 審閱歸檔 — 登記冊：新增 reconcile.google_projection_grace（f-22），趨勢、動能已做＋sources 換版（PR #140）

- **Repo**：bcup02/trade-alerts
- **PR**：#140，head `bc0f445e682f83d41d6c39789118e86afef16d03`，base `9d24836d3d4cfb45c64a769b89b00a81ecc1eafa`（main），squash 合併為 `67169d0`
- **審閱者**：Perplexity — 一輪 **PASS**
- **CI**：pytest = success（run `37592089967`；689 passed，+0）

## 做了什麼

新增一格 `reconcile.google_projection_grace`（共用庫 v0.27.7 的 Google 表對帳寬限，f-22）：趨勢、動能已做（證據綁 A1 正式機（新）：/opt 檔案 blob 與 operations commit 同檔、venv trade-alerts 0.27.7 的對帳模組 blob `fca13c4` 與 tag v0.27.7 同檔、部署後手動對帳 RECONCILED；限制照實寫：部署時空手、沒有實際看到寬限擋掉一次誤報）；競賽不適用（自己的 `reconcile_google.py:49` 3600 秒寬限，PENDING 在維運通知是 warn 級、調倉時是否會短暫告警還沒查）；加密未做（x3，仍釘 v0.15.0）。sources 動能 `4780bd9`→`71ccee3`、趨勢 `9e3ae05`→`3520da6`；既有 134 筆帶行號引用逐筆比對舊新行文字全相同（兩次換版之間策略 src 沒變）。

## 審閱過程

一輪 PASS。審閱者直接比對新舊提交的 src blob（動能 `google_reconcile.py` 48433a6、趨勢 `google_reconcile.py` 7f854ee 等）確認引用行號不變，核對 A1 blob 與 tag v0.27.7 對照、所有新寫時間（台北 16:07／JST 17:07 等）沒有把 JST 誤標成台北、競賽與加密的理由、recent_changes 只標真正改的項目。這次依 #136 的教訓一開始就把被引用檔原文、逐筆比對表與 JSON 完整原文貼進 PR 留言，沒有被要求補證據。

## 審閱者標明的界限

- PR 留言原寫「79 組唯一位置」，審閱者提到的數字與我表格的組數不同；他以 blob 比對為準，結論不受影響。
- A1 的 /opt blob 與實機狀態是開發端唯讀取得的觀察紀錄，審閱者沒有重新操作 A1。
- done 不代表已在 A1 看過寬限擋掉一次誤報；那要等下一次動能進場。
- PASS 不授予合併後重發 artifact 或部署權限。

## 隔離聲明

本 PR 只動 `src/trade_alerts/catalog/fleet-rollout-registry.json` 與由它產生的一張頁面；沒有程式碼、deploy、tests 變動，不需部署。審閱者只讀 GitHub 與 PR 留言；開發端在 A1 的動作都是唯讀（git hash-object、pip／python 讀版本、journalctl）。
