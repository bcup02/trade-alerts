# Perplexity 審閱歸檔 — 登記冊：資金費同步（趨勢、動能）上 A1 改已做＋sources 換版（PR #136）

- **Repo**：bcup02/trade-alerts
- **PR**：#136，head `335519da44f52a670e5a368784a701bd45ceb79f`，base `1eb46ca9c2af5b97014c61e7af2fca0b04e4455b`（main），squash 合併為 `2eebe19`
- **審閱者**：Perplexity — 兩輪，同一個 head：首審 **BLOCK**（必要獨立核驗未完成，不是已確認失配）→ 補證據留言後複審 **PASS**
- **CI**：pytest = success（run `37572984427`；674 passed，+0）

## 做了什麼

`reconcile.funding_fee_sync` 趨勢、動能由 pending 改已做（證據綁 A1 正式機（新）：`/opt` 七個檔案 blob 與 operations commit 同檔相同、venv toolkit 0.4.0、timer enabled、實際執行紀錄，時間同時標台北與 A1 日誌 JST，限制照實寫：多頁分頁沒用真資料驗過、A1 帳戶 2026-09-19 前查不到資金費）；`sources` 趨勢 `5958bbf`→`9e3ae05`、動能 `97f5ebb`→`4780bd9`；既有帶行號引用 127 筆（72 組唯一位置）逐筆比對舊提交行文字＝新提交新行號行文字（行號不變 102、改變 25＝4 組，全是趨勢 `scripts/repair_bot.py`，#103 加了行；不一致 0）；兩張頁面重新產生；`recent_changes` 兩個 completed。

## 審閱過程

首審 BLOCK：審閱者讀得到 diff 與前次表格，但讀不到舊新兩份完整原文，無法自行重建行號對應，所以不肯把「127 筆全部相同」當成 reviewer 已驗證；結論明講不是已確認失配。開發端的處理：把趨勢 `repair_bot.py` 舊新兩個提交的完整原文（含行號與 blob SHA）、逐筆引用表（含所在函式）與新增資金費引用的 exact-source 原文貼進 PR 留言，沒有新 commit。複審 PASS：審閱者去掉行號重建 bytes，兩個 blob 重算全同，四組位移（+1／+19／+25／+25）逐行索引加 AST 比對完整行文字與所在函式都一致，未位移部分抽樣也無差異。

## 審閱者標明的界限

- A1 執行、timer enabled、toolkit 0.4.0、Google 寫入是開發端的部署觀察紀錄，審閱者沒有重新操作 A1。
- 未位移引用是抽樣加完整檔案或 subtree blob 身份比對，不是重新逐行審計所有來源檔案。
- 審閱者沒有自行執行 `render_guides.py --check` 或本地 pytest，依同 head 的 GitHub Actions。
- 「已做」只代表正式分支／A1 已部署運行，不代表多頁真資料驗收或歷史缺口已補回。
- 非阻擋：產生頁那句「2026-10-07 對四個 repo 逐項盤點」是 `render_guides.py` 範本固定句、用 `updated_at` 帶日期，本 PR 沒有逐項刷新所有 pending 格；刻意沒改。
- PASS 不授予合併後發布或部署權限。

## 教訓

審閱者拿不到來源檔原文時，會把表格當成開發端自述而不計為獨立驗證。登記冊換 `sources` 的 PR 送審時，一開始就把舊新兩份被引用檔的完整原文（含行號與 blob）貼進 PR，不要等到 BLOCK。

## 隔離聲明

本 PR 只動 `src/trade_alerts/catalog/fleet-rollout-registry.json` 與兩張由它產生的頁面；沒有程式碼、deploy、tests 變動，不需部署。審閱者只讀 GitHub 與 PR 留言，沒有接觸實機。開發端在 A1 的動作都是唯讀（`git hash-object`、`pip show`、`systemctl cat`、`list-timers`、`journalctl`）。
