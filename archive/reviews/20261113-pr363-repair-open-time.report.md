# PR #363 審閱歸檔：補記晚的開倉列，平倉早於開倉的判準改用成交時間（v0.30.36）

- PR：bcup02/trade-alerts #363；squash `4e31b83`；tag `v0.30.36`（打在 squash commit）；審閱 AI：ChatGPT；結論：BLOCK 一輪後第二次 PASS（head `5010644`，CI run 43374158403，1666 passed）。
- 範圍：`verified_close_backfill.py`（`assess_repair` 的開倉時間下界）、`repair_runner.py`（`RepairAdapter.opened_at_is_fill_time`）、錯誤目錄 sources 行號 +1、兩個測試檔；版本 0.30.36。

## 緣起
2026-11-13 開發機演練（V11 DOGE）：補記的開倉列 `event_epoch_ms`（記帳時間）晚於實際平倉成交，`assess_repair` 判「a closing fill predates the trade_open」，修復機器人不處理，只能手動補寫平倉。V11 端對應修正是 ed-seykota-systematic-trend-following#236。

## 審閱歷程
| 輪 | head | 結論 | 內容 |
|---|---|---|---|
| 1 | `ce65d37` | BLOCK | 363-01：只憑「opened_at 比記帳時間早 ≥ 1 秒」就信它，各策略的 `opened_at` 可能不是成交時間，會放行前一部位的平倉；363-02：`event_epoch_ms` 為負數或布林時被當有效時間（base 就有的缺口）。 |
| 2 | `5010644` | PASS | 新增 `opened_at_is_fill_time`（`assess_repair`、`RepairAdapter` 預設 False，runner 轉交），轉接層明確保證才採用 `opened_at`；`_written_ms` 對布林、負數、零、非數字、NaN fail closed；補邊界（999／1000／1001 ms）、七種無效值、多筆開倉、runner 端到端測試。 |

## 已知缺口與後續
1. 共用庫預設仍不信任 `opened_at`；各策略要開旗標須在自己的 PR 證明所有 `trade_open` 列的時間來源。V11 在改釘 v0.30.36 後開（ed-seykota#236 跟進）。
2. `find_open_event` 的 fold 仍用原始 `event_epoch_ms`，未改。

## 教訓
1. 共用庫的安全閘門遇到「各策略語意不同」的欄位，預設要拒絕，由知道來源的轉接層明確保證才放寬。
2. 新增一個時間／數字欄位判斷時，一併檢查布林、負數、NaN，不只缺值。
3. 錯誤目錄 sources 行號會跟著程式位移，改 `repair_runner.py` 欄位要連帶調整。
