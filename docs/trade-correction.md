# 帳本更正事件（`trade_correction`，trade-correction/v1）

> 2026-09-24 建立（機隊工程進度 h4）。起因：趨勢策略 2026-09-21 同一個 clientOrderId 成交兩張、帳本只記一張，
> 平倉又只記了 0.008（實際 0.011）；另外 09-19 加碼與 09-21 進場的價格、手續費是估算值。

## 為什麼要一種新事件

帳本只能往後加。要把一筆記錯的交易改成跟交易所一致，不能改舊紀錄，也不能單純再補一筆開倉或平倉——
現有的讀帳本程式各有規則會擋掉或誤判：

| 讀帳本的地方 | 規則 | 補一筆開倉／平倉的後果 |
|---|---|---|
| 帳本對交易所（`exchange_ledger_compare`、各策略 compare） | 事件的 `order_id` 算「已記錄」；部位＝開倉量−平倉量 | 補在結案後的開倉讓帳本以為還有部位 |
| 交易彙整（`fold_ledger_trades`） | 同一筆交易以第一筆 `trade_close` 為準 | 補的平倉被忽略 |
| Google 表投影（策略轉接器） | 同一筆交易只能有一筆平倉事件 | 判定歧義、停止投影 |
| Google 表接收端 | 平倉確認後內容不同一律 `trade_close_conflict` | 被拒 |

所以更正是獨立的一種事件，由共用模組 `trade_alerts.trade_correction` 定義、產生與套用。

## 格式

```json
{
  "event_type": "trade_correction",
  "schema_version": "trade-correction/v1",
  "trade_id": "BTCUSDT-1142206675339", "symbol": "BTCUSDT", "side": "long", "execution_mode": "LIVE",
  "reason_code": "DUPLICATE_ENTRY_UNRECORDED | UNRECORDED_FILL | ESTIMATED_FILL_SUPERSEDED",
  "reason": "給人看的原因",
  "corrects_event_ids": ["被重述的開倉與平倉 event_id"],
  "exchange_order_ids": ["這筆交易在交易所的所有單號"],
  "added_fills": [{"order_id": "…", "side": "buy", "quantity": 0.003, "price": 85877.5, "fee": 0.12881625, "time_ms": 0}],
  "previous":  {"entry_volume": …, "exit_volume": …, "entry_price": …, "exit_price": …, "entry_fee": …, "exit_fee": …,
                "total_fees": …, "gross_pnl": …, "net_pnl": …, "return_on_margin": …, "exit_order_id": …},
  "corrected": {同上欄位，交易所數字},
  "evidence": {"source": "…", "fills": [交易所成交原始列]}
}
```

`event_id` / `event_time` / `event_epoch_ms` 由各策略的帳本寫入器加上。

## 規則

- **只從交易所成交算**：`build_trade_correction` 用 reconcile-source/v1 的成交列重算整筆交易（加權均價、手續費、毛／淨損益、保證金報酬），
  不接受手打數字。帳本已記錄的每張單都必須在成交列裡；進出量必須相等；有交易所 `realized_pnl` 時毛損益要與它一致（誤差 0.01）；
  手續費必須是 USDT。
- **只能更正已平倉的交易**，且更正後進出量相等——所以**永遠不改變帳本推得的部位**。
- **`previous` 必須等於目前生效的數字**：套用時對不上（例如同一筆更正追加兩次、或針對別本帳本產生）就拋 `TradeCorrectionError`，
  讀帳本的程式把它當成對帳失敗顯示出來，不會默默套一半。第二次更正會自動以第一次更正後的數字為 `previous`（鏈狀）。
- **套用方式**：`apply_trade_corrections(events)` 把該交易第一筆 `trade_close` 換成更正後的副本（`corrected_by` 記更正的 event_id），
  `order_id` 換成 `corrected.exit_order_id`；`correction_order_ids(events)` 給出更正涵蓋的單號，算作已記錄。
  共用的 `recorded_order_ids` 與 `fold_ledger_trades` 已內建。

## Google 表：`correct_close_v2`

- 來源驗證的事件類型是 `trade_correction`；投影＝策略原本的平倉投影欄位，數字換成 `correction_projection_fields(event)`，
  再加 `corrects_payload_digest`（目前在 Google 表生效的那一版投影的摘要：原本的平倉，或上一次更正）。
- 接收端只在「那筆交易的平倉已確認、而且 `corrects_payload_digest` 等於目前生效版本」時覆寫；同內容重送回 idempotent；
  否則 `correction_base_mismatch` / `close_not_confirmed` / `correction_projection_invalid`。稽核表記 `trade_correction CONFIRMED`。
- 更正會覆寫平倉欄位，外加 G（整筆交易加權進場價）、I（整筆數量）、U（備註：更正原因與前後數字）。
  既有狀況（另列待辦）：一般的 `update_close_v2` 不寫 G／I，有加碼的交易在 Google 表上 G／I 仍是第一次進場的價量。
- **部署**：接收端是機隊共用的 Apps Script，改版後要由使用者在 Google Apps Script 編輯器重新部署，程式庫發版不會自動生效。

## 人工工具與修復機器人

同一個 `build_trade_correction` 給兩種呼叫端用：各策略的兩段式人工更正工具（預覽→帶確認碼寫入），
以及修復機器人自動更正（g1：帳本少記交易所成交時，能完整由交易所成交重述的已平倉交易自動更正；
判斷是策略自己重複送單時仍立即通知人追根因；無法重述時通知人工並附步驟）。
