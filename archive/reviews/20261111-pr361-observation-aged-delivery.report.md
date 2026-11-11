# PR #361 審閱歸檔：超過 14 天的事件查不到送出紀錄不再判失敗（v0.30.35）

- PR：bcup02/trade-alerts #361；squash `50bfdf5`；tag `v0.30.35`（打在 squash commit）；審閱 AI：ChatGPT；結論：BLOCK 一輪後第二次 PASS（head `51473a6`，CI run 43027339880，1644 passed）。
- 範圍：`scripts/observation_watch.py`（f-38 與事件日誌型檢查 `_strategy_event_result`：f-35／f-37、f-30、g2）與測試；版本 0.30.35。

## 緣起
2026-11-11 台北 16:30，已結案的 f-38、f-35／f-37 翻成失敗並響 LINE。維運通知的送出紀錄（`_export.<目標>.delivered`）送出後至少保留 14 天就清掉，10/28 的動能 `PROTECTION_UNVERIFIED` 事件剛滿 14 天，偵測程式把「查不到紀錄」當成「沒送出」。A1 維運通知日誌沒有重送。

## 審閱歷程
| 輪 | head | 結論 | 內容 |
|---|---|---|---|
| 1 | `70f0960` | BLOCK | 361-01：過期分支排在 `ai_pending`（第二則欠送）判斷之前，把仍欠送的第二則遮住；361-02：過期＋查不到紀錄一律回可結案，等於把「從未證實送達」當機器查證通過。 |
| 2 | `51473a6` | PASS | 過期分支內先判第二則欠送（`overdue:<id>`）；檢查自己的 `extra.proven` 記住「先前真的查到送出紀錄」的事件，只有它們過期後可沿用原結論與原 key，否則 `unproven:<id>`（需要你確認、不可結案）；所有回傳路徑都帶 `proven`。 |

## 已知缺口與後續
1. `proven` 以 event_id 為鍵，跨策略 ID 碰撞理論上可能套錯（未發現實際碰撞）；建議之後改 `(策略, event_id)`。
2. `proven` 只留最新 50 筆，更舊的會重新落入 unproven（偏保守）。
3. 部署：開發機偵測副本單檔換版（舊版備份 `observation_watch.py.bak-pre-v03035`）；換版前先 `--dry-run` 試跑。因為開發機那份沒有 `proven` 記憶，f-38、f-35／f-37 換版後各以 `unproven` 出現一次，核對先前結案證據後已 `observation-report ack`；LINE 可能多響一則。這次一併帶上 main 的其他檢查（含 `dev-v11-cycle`＝進度頁 phase-v10-p3）。

## 教訓
1. 外部系統會清掉的證據（有保留期限的紀錄）不能當「沒發生」的證據，也不能當「發生過」的證據；要自己記住先前看到的結果（`extra.proven`）。
2. 新增的「放行」分支要排在所有「失敗」證據之後，且不能把證據缺口自動寫成通過。
