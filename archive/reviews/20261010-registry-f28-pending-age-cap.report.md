# Perplexity 審閱歸檔 — 登記冊新增「對帳收斂中最多等 24 小時」能力（PR #160，f-28）

- **Repo**：bcup02/trade-alerts
- **PR**：#160，head `2ea52cab3b4ec45573163da2fa1870be7b5cfd9b`，base `7e4885e460fb0cb1ef3edac15196351dfd649805`（main），squash 合併為 `e862914`
- **審閱者**：Perplexity — 首審 **PASS**（一輪）
- **CI**：pytest = success（run `38054863617`；801 passed，baseline 801，沒有新增測試）。不需要部署、不發 tag

## 內容

新增能力 `reconcile.pending_age_cap`：競賽 **已做**（AI-for-column/btc-bull-market-competition#53，2026-10-10 台北 21:10 上 A1，operations `0025f3c`，證據引用 `reconcile_compare.py` :65、:207、:179、:258、:294、:188；A1 唯讀量測與手動一輪對帳 RECONCILED；限制：A1 沒有觸發過超過 24 小時的分支，只在測試與開發機實測）；動能 **未做**（新階段 `f-28b`：共用庫「位置對帳標記沒結清就一直 PENDING」沒有時間上限）；趨勢、加密 **不適用**（PENDING 只在帳本事件比交易所快照新時出現，下一輪恢復）。`sources` 競賽 `70630a1→0025f3c`；f-18 新檢查 42 處引用 0 shifted、0 unpaired、1 changed（`runner.py:597` 多行 lambda，`runner.py` 新舊 blob 相同 `4278c03`，人工確認）。`recent_changes` 2 筆；兩張登記冊頁面重新產生。

## 審閱結論重點

- 審閱者直接讀競賽 `0025f3c` 原始碼核對六處引用；動能 `src/reconcile_compare.py` 的 `include_pending_markers=True` 與共用庫 `ledger_reconcile.py` 的 `unsettled_pending_markers`／PENDING 分支確認動能 pending 站得住；趨勢 `compare.py:207、225–228`、加密 `reconcile_compare.py:61–69` 的不適用理由成立（針對「長期未結清標記／批次」，不是宣稱永遠不 PENDING）。
- `0025f3c` 與競賽 operations 相同；`reconcile_compare.py` blob `1b4ff00a…`；JSON 逐欄比較：原有 30 項能力與 59 筆錯誤清單登記內容全部相同，只新增 1 項能力與階段 `f-28b`；兩張產生頁與 JSON 一致（CI 的 render check）。
- A1 的 `/opt`、模式檔、systemd 清單是我貼在 PR 的量測摘錄，審閱者沒有連線 A1：只獨立證實 GitHub 上提交與 blob；登記冊已把「A1 部署與一般對帳成功」與「超過 24 小時的分支只在測試／開發機驗證」分開寫。
- 措辭建議（未改）：手動啟動既有 `reconcile-fetch` oneshot 不等於檔案層面唯讀（會更新對帳快照與狀態輸出）；未來 A1 證據要分別標示「唯讀檢查」與「觸發既有 oneshot」。

## 教訓

- 手動啟動既有 oneshot 驗證不是「唯讀」；A1 動作的描述要誠實分類。
- 做一項功能時，四支策略一起查程式再登記（做／未做＋預定關卡／不適用＋理由），這次查到動能共用庫還有一條沒上限的路徑，所以登記成未做而不是漏掉。

## 隔離聲明

只動 `src/trade_alerts/catalog/fleet-rollout-registry.json` 與兩張產生頁中的一張；沒有程式、錯誤清單、共用庫或部署變動。
