# 審閱歸檔 — 編號衝突的開倉列／成交列停放（PR #277，共用庫 v0.30.19，f-64）

- **Repo**：bcup02/trade-alerts
- **PR**：#277，head `3b55473569a3b1956fd487c4922bf8eac7401389`，base `e9060352492f6ba2c43baca59b018f767a7df824`（main），squash 合併為 `caa11dacc975c08605b3bdf4b1e4d3478c544ea3`；tag `v0.30.19`（指向該 squash）
- **審閱者**：ChatGPT — 首審 PASS，共 1 輪
- **CI**：pytest = success（run `39894909973`；1475 passed，baseline 1471，+4 新測試）

## 做了什麼

`projection_outbox` 新增：開倉列（`append_open_v2`）或成交列（`append_fill_v2`）連續 3 次被 Google 表接收端回 `trade_id_conflict` 就記 `REJECTED`（原因 `trade_id_conflict_parked`）停放，後面的紀錄照常送出；停放時寫一筆 R1 事件 `PROJECTION_TRADE_ID_CONFLICT_PARKED`（不通知）。錯誤清單新增 ERR-069；兩張登記冊新增該列（四支策略都列未做，phase `f-64`）；版本 0.30.19。

## 重點

- 起因：開發機競賽 10/8 起被一筆編號衝突的舊成交卡住佇列 15 天（補送步驟重排了表上早有舊動作列的成交）；共用庫把 `trade_id_conflict` 當可重試。競賽側根因修正是競賽 #74。
- 門檻取 3（不是 12）：接收端答案是確定性的、策略 drain 每輪最多試 3 次；審閱者認為合理，並註明代價：停放後不再自動重送，要靠既有 `requeue_rejected_projection_intents` 重新排入。
- 審閱者的非阻斷建議（未做）：替 `trade_id_conflict_parked` 的重新排入加專屬測試（重新排入後若仍衝突會重新累計三次）；目前由通用 requeue 測試與停放測試間接覆蓋。
- 審閱者標明界限：沒有本地 checkout、沒有重跑 pytest（以 CI 原始日誌為準）；事件日誌是 best-effort（既有設計）。
- PASS 只授權合併，不授權發版、改釘或部署 A1。

## 隔離聲明

審閱者只讀 GitHub 的 PR diff、原始碼、測試與 CI 日誌；沒有接觸 /opt、/etc、/var/lib、systemd、交易所、Google、任何實機 state 或帳本，沒有合併、推送或部署。開發端：只動共用庫與登記冊資料，未部署；合併後發 tag v0.30.19。
