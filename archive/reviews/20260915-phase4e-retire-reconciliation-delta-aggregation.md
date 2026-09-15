# 審閱歸檔：retire the reconciliation_delta aggregation plan (Phase 4e)

- **PR**：`bcup02/trade-alerts` #19
- **feature 分支**：`phase4e-retire-reconciliation-delta-aggregation`，head `5e9785898c5c89690d8e077ecc17ce161f9e6c0a`
- **base**：`main` @ `d8bf6ac`
- **squash 合併為**：`f605cbb`（`gh pr merge --squash --delete-branch`）
- **審閱者**：Perplexity — **結論 `PASS`**（連結器直讀，一輪）
- **CI**：`pytest` = success（161 passed，baseline 161，delta 0——純文件修正）
- **對應 patch**：`20260915-phase4e-retire-reconciliation-delta-aggregation.patch`
- **部署**：不需要（trade-alerts 是純函式庫，無執行期足跡）

## 背景

全機隊錯誤處理重建 Phase 4e 開工，原計畫（§4.5/4.6）是把 `reconciliation_delta`（每筆平倉時
本地淨損益跟交易所回報損益的差額）接進「聚合偏離才開請求」的邏輯。開工前先去 trading-main 拉
真實帳本資料驗證：momentum 連續 17 筆、my-crypto 僅有的 1 筆有效資料，`reconciliation_delta`
**每一筆都精確等於 `-(entry_fee + exit_fee)`**，誤差在小數點第 6 位。

## 發現與結論

- **根因**：交易所回報的 `exchange_profit` 是手續費前的毛損益，本地 `net_pnl` 是手續費後的淨
  損益，兩者相減從定義上就只會是負的手續費——不是雜訊，是已知、良性、方向永遠一致的系統性
  偏差。不管怎麼調公式，聚合起來永遠是同一個已知原因，沒有需要人介入的訊號可抓。
- **為什麼觀察不到殘留雜訊**：這個指標原本想抓的問題（my-crypto 程式碼開頭第 13 點：本地進
  出場價格跟交易所現實脫節，錯誤會沿用進未來的移動停損計算）已經被 my-crypto 2026-08-22 的
  另一個修正（第 14 點：`_fetch_order_info()` 改用交易所確認過的 `dealAvgPrice`/`totalFee`
  入帳）從源頭堵住了。
- **決定**：`reconciliation_delta` 永久停在 §4.5 事件日誌這一層，**不建聚合邏輯、不接 §4.6
  請求佇列**。

## 這一支做了什麼

1. `docs/fleet-error-catalog.md`：§3.4 表格加註「P4e 定案不聚合」；§4.5 拿掉「聚合偏離才開
   請求」的承諾，指向新增的 §4.7；新增 §4.7 完整記錄盤查證據、根因、撤回理由。
2. `catalog/fleet-error-catalog-v1.json` 的 `MYC.RECONCILE_DELTA_EXCEEDED` 條目：`sources`
   行號更新、`current.notify` 改成 audit-only 描述、`human_action` 改寫成永久不升級、
   `lands_in_phase` 3→4、`rationale` 補上發現與撤回說明。
3. **刻意不改**：schema（形狀沒變）、`test_fleet_error_catalog.py`（沒有不變式檢查這段文字）、
   §4.6 請求佇列基礎設施本身（留給未來別的訊號源）。

## Perplexity 審閱（一輪 PASS，逐項核對）

- **§4.7 數字論證**：確認 `reconciliation_delta = net_pnl - exchange_profit =
  -(entry_fee + exit_fee)` 的推論鏈完整自洽，不是把「差額恰好等於費用」誤判為異常。
- **三處一致性**：§3.4/§4.5/§4.7/JSON 五個欄位（`current.notify`/`human_action`/
  `auto_action`/`rationale`）全部採用同一個最終模型（保留測量、永不聚合/通知/升級）。額外做
  了 repository-wide 搜尋，確認舊措辭「聚合偏離才開請求」只殘留在 base commit 與歷史 patch，
  現行文件已無矛盾殘留。
- **JSON 完整性**：只有這一個 entry 的五個欄位值被改，`code`/`title`/`project`/`current.latch`/
  `verdict`/`risk_tier`/`auto_action`/`resume` 及其他條目未受影響，結構完整。
- **§4.6 描述仍正確**：基礎設施保留、已明確排除 reconciliation_delta 作為 producer，沒有
  「queue 存在」跟「此 R0 measurement 仍會用 queue」的矛盾寫法。
- **隔離聲明**：僅讀取 PR metadata/diff/CI，未接觸 `/opt` `/etc` `/var/lib`、systemd、交易所、
  Google、實機帳本，未寫入任何內容。

## 依賴關係

`AI-for-column/my-crypto-bot` #45（實際程式碼改動：`alerts.publish` → `append_fleet_event`）
依賴這份文件定案的結論；兩份 PR 各自獨立審閱、無版本 pin 依賴。
