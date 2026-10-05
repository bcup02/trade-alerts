# Perplexity 審閱歸檔 — 競賽 ERR-025 改 R2「當天重試、第 3 次失敗才通知」；ERR-043 補 UNKNOWN 說明（PR #131，v0.27.5）

- **Repo**：bcup02/trade-alerts
- **PR**：#131，最終 head `6eb0c94e775dad66510a4a3d309505a0d2b69cc8`，base `e9f0261f1368375cb66d07833df01d04b7e14b0c`（main），squash 合併為 `b82b95c`，tag `v0.27.5`
- **審閱者**：Perplexity — 三輪：`f213efa` BLOCK（F1 通知文字漏了「失敗次數無法保存就立即升格」路徑、「已送出」用詞超過證據）→ `4c84a70` BLOCK（F2 文字宣稱寫不進去就升格，競賽實作 save 失敗時仍重試）→ `6eb0c94` **PASS**
- **CI**：pytest = success（最終 run `37331942399`；674 passed）

## 做了什麼

使用者 10/5 決定（進度頁 t9）：競賽每日調整失敗時當天重試並通知。資料變更：ERR-025 `BTC.RUNTIME_CYCLE_FAILED` 由 R0 改 R2（三種情況：還沒嘗試送單且次數記得下來 → 15 分鐘一次、當天最多 3 次、第 3 次才升格；已嘗試送單 → 不重試、立即升格；失敗次數無法讀寫 → 不重試、立即升格；exit 1 重跑／exit 75 不重跑）；ERR-043 補 UNKNOWN 連續 3 次刷新才通知（ops-notify #37）；登記冊競賽「行為」由已做改待辦（新行為只在開發機）、新增 phase `t9-competition-retry`；版本 0.27.5。

## 審閱過程

1. 首審 BLOCK（F1）：競賽實作的第三條路徑（計數狀態無法讀取 → 第一次就升格）沒被文字涵蓋；「已送出單」超過 `orders_attempted` 能證明的範圍。修正：ERR-025 分三種情況寫清楚，用詞改「已嘗試送單」；附上競賽實作完整 diff 作為證據（`main()`、成功清除計數）。
2. 複審 BLOCK（F2，**競賽程式的真 bug**）：`_record_run_failure` 在 `save_state()` 之前就把次數存進 `attempt`；存檔拋例外時只記 log，`attempt` 仍為 1 → retry=True、R0、不寫運行狀態 ERROR；連續三次存檔失敗都是重試。修正（競賽 repo `94efaf2`）：次數成功寫進狀態檔後才採用，任何例外把 `attempt` 設為 None；新增回歸測試；ERR-043 用詞改成「連續達到設定的輪數（預設 3 輪）」。
3. 三審 PASS：審閱者以原函式做 21 次失敗路徑呼叫（正常、讀 problem、讀例外、存檔 PermissionError、存檔 ENOSPC、寫後才拋例外、已嘗試送單）全部符合文字。

## 審閱者標明的界限

- 這些是失敗決策的 probes，不是實機磁碟故障測試；不保證磁碟全滿時事件、心跳與通知管道仍可寫入或送達。
- 競賽實作未合併、未獲獨立 implementation acceptance，競賽正式 PR、釘版、部署另審。
- PASS 不授權部署或交易操作。

## 隔離聲明

審閱者唯讀；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或實機帳本。合併不代表任何主機部署。
