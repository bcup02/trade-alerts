# PR #404 審閱歸檔：觀察偵測 dev-v11-cycle 結案標記固定值＋分頁名稱改實際名稱

- 審閱者：ChatGPT；**共 2 輪：BLOCK、PASS**（結論行「審閱PR#404結論：PASS」）
- 被審 head：29d48d4ecb9e8227b5d849905273e7663b93c947；base：7d3b469；squash：72b4ad3；CI pytest run 44862965792，1715 passed（前次 1713）
- 變更：`scripts/observation_watch.py`（`dev-v11-cycle` 的 key 由 `str(len(trades))` 改固定 `cycle-ok`、內文改『競賽策略・流星版』分頁、`SHEET_NAMES["seykota"]` 改『舊趨勢策略』）、`src/trade_alerts/ledger_integrity.py`（註解）、`tests/test_observation_watch.py`、`tests/test_sheet_name_cjk.py`；不改版本號
- 起因：2026-11-21 演練讓開發機流星版成交列 6→10→23 筆，已結案並 ack 的里程碑因 key 綁筆數而重發兩次，內文還寫已不存在的『趨勢策略』分頁。

## 各輪結論
1. 第 1 輪 BLOCK-404-01：固定 key 後，已 ack 的 OBSERVED 經 WAITING 再成立時仍被舊 ack 壓制，與 PR 描述「條件消失再回來才是新事件」不符。→ 判斷為 PR 描述與註解說錯，f-71（已 ack 的同一結果從 WAITING 回來不再通知，既有測試鎖住）才是正確契約；更正註解與描述，不新增輪次識別，補兩個走 run_checks→notify→ack 的狀態機測試。
2. 第 2 輪 PASS（確認 f-71 語義）。

## 教訓
- 通知結案標記（ack key）不可綁會隨時間增長的量（成交筆數），要綁固定的結果身分；改 key 後部署前要預期會再跳一次，部署後當場重新 ack。
- 寫 PR 描述與註解前先對照既有狀態機契約（f-71），別自創「再回來是新事件」之類的說法。
- 文字中的 Google 分頁名要用實際分頁名：『競賽策略・流星版』、『舊趨勢策略』；已沒有『趨勢策略』分頁。
- 審閱隔離：未接觸 /opt /etc /var/lib systemd 交易所 Google 實機帳本；沒取得 raw CI log，依 job metadata 與 sticky 摘要。
- 部署：2026-11-21 台北 12:07 單檔換到開發機偵測（備份 `observation_watch.py.bak-20261121`），重新 ack `observed:cycle-ok`。
