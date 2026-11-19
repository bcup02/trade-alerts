# PR #402 審閱歸檔：登記冊——流星版 45 格改已做、sources 換到 A1 現行 219f87d（v0.30.50）

- PR：bcup02/trade-alerts #402；squash `7fc2cc5`；審閱 AI：ChatGPT；結論：第 1 輪 BLOCK（head `bb07a20`，base `f8d10cc`）、第 2 輪 PASS（head `c01b35e`，CI run 44482475049，1710 passed）；tag `v0.30.50`。
- 範圍：流星版 128 格逐格對照 A1 實際執行的單元與讀數——45 格 built→done（verified_at 2026-11-19，limit 說明 A1 沒遇過的情境）、7 格→n/a（時鐘軸 2 格、維運通知五條狀態規則的事件欄位）、67 格留 built（要靠每日計時器才跑得到，預定關卡 meteor-unpause）、2 格 pending；`sources.trend-meteor` 換到 A1 現行 `219f87d`；兩處「檔案:行號」引用（execution.py:60、google_reconcile.py:157）逐行重核。

## BLOCK-402-01（已修）
五條 FLEET.OPS_* 規則（LEDGER_DIVERGED、RUNTIME_ALERT、UNIT_FAILED、EXPORT_UNAVAILABLE、STATUS_STALE）的流星版 emits_event 被改成已做，但維運通知直接讀狀態檔、不經事件日誌，其他四支都是不適用；證據只證明「狀態被讀到」，不是事件日誌寫入。第 2 輪改 n/a 並新增守門測試（7 條 FLEET.OPS_* 的 emits_event 在所有策略都必須是 n/a）。

## 教訓
1. 改「已做」前先對照同規則其他策略格子的語意（行為與事件欄位走的資料流不同），不能把「讀數正常」當成「寫了事件」。
2. 只讀 A1 單元與讀數的查證，證據的邊界是「這條路徑有沒有被實際走過」；沒走過的用 limit 明講，需要每日流程的一律留 built。
3. 摘要的格數要用實際總數（128），不要拿某一類的數字（117）當全部。
