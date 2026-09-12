# Trade Alerts 投資人整合契約 v1

**狀態：第一版草案。** 本文件是跨交易專案的公開資料契約；它描述事件推播所需的資料，不包含任何交易所憑證、聊天平台秘密或下單指令。JSON 的機器時間欄位使用 ISO 8601 UTC，例如 `2026-08-19T08:00:00Z`，以利跨專案排序與計算；LINE／Telegram 面向投資人的文字畫面則必須轉為 **Asia/Taipei（UTC+8）**，格式為 `年-月-日 時:分`，例如 `2026-08-19 16:00`。

> 本文件原本還涵蓋唯讀投資人查詢（`portfolio_snapshot`／`closed_trades` 資料形狀、查詢命令對映、Seykota provider 對映）。那條路徑（`InvestorQueryController` 與相關 renderer）從未被任何消費專案採用——各專案後來都各自實作了本地渲染——已在 Phase 2c 死碼清理中移除；此文件同步只保留仍存活的事件契約（§1-3）。

## 1. 設計目標與安全界線

每個交易專案以唯一的 `project_id` 識別自己，透過 `trade-alerts` 發送標準化事件。

契約只允許**通知**。`trade-alerts` 不得因通知失敗改變策略決策，也不得透過此契約執行任意 shell、修改秘密、轉帳、下單、解除保護單或啟用實盤。交易專案仍負責風控與交易模式閘門；每一份事件都必須明確帶有 `execution_mode`，而 `DRY_RUN` 是目前唯一允許的模擬測試值。

## 2. 版本規則

根契約版本以 `schema_version` 表示，初版固定為 `1.0`。`1.x` 只可新增選填欄位、事件類型或 enum 值，不可刪除、改名或改變既有欄位語意。接收端遇到未知選填欄位或未知事件類型時，應保留原始資料並以通用訊息呈現，不得拒絕整個訊息。只有破壞性變更才增加主版本，例如 `2.0`。

為支援漸進遷移，接收端必須接受舊版 `AlertEvent` 的 `event`、`message`、`critical`、`system`、`occurred_at`、`fields` 介面。舊事件沒有標準 envelope 時，adapter 應把 `system` 對映為 `project_id`，把 `occurred_at` 對映為 `occurred_at`，並將其餘資料放入 `data`；缺少的欄位不得猜測。

## 3. 事件 envelope

每次推播是一個 JSON object，至少包含以下欄位：

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---:|---|
| `schema_version` | string | 是 | 目前為 `1.0`。 |
| `event_id` | string | 是 | 專案內唯一且可重試去重的事件 ID。 |
| `event_type` | string | 是 | 標準事件名稱。 |
| `project_id` | string | 是 | 穩定的專案識別碼，不使用秘密。 |
| `project_name` | string | 是 | 給投資人看的專案名稱。 |
| `occurred_at` | string | 是 | UTC 發生時間。 |
| `execution_mode` | enum | 是 | `DRY_RUN`、`PAPER` 或 `LIVE`；現階段交易專案測試只可使用 `DRY_RUN`／`PAPER`。 |
| `severity` | enum | 是 | `INFO`、`WARNING`、`CRITICAL`。 |
| `message` | string | 是 | 人類可讀摘要，不得包含 token 或密碼。 |
| `data` | object | 否 | 事件特有的結構化欄位。 |
| `presentation` | object | 否 | 供手機渠道使用的選填呈現擴充；不改變 `data` 的機器可讀語意。 |

若事件提供 `presentation.format = investor_mobile_v1` 與非空的 `presentation.text`，LINE／Telegram 必須直接顯示該文字，不可另行附加 `event_type`、`event_id`、`trade_id`、`order_id`、`schema_version`、`project_id`、`ledger_event_type`、原始錯誤內容或其他內部欄位。文字必須使用投資人語言與 **Asia/Taipei（UTC+8）** 的 `年-月-日 時:分` 格式；未使用此選填擴充的舊事件維持既有呈現，以確保漸進遷移與向下相容。

標準 `event_type` 包括 `SYSTEM_HEALTH`, `ENTRY`, `ADD`, `EXIT`, `PROTECTIVE_ORDER_UPDATED`, `ENTRY_SKIPPED`, `PNL_UPDATE`, `SAFE_HALT`, `ERROR` 與 `TEST`。策略可以使用專案前綴的特有事件，但必須保留通用 envelope。

交易事件的 `data` 建議使用：`symbol`、`market`、`timeframe`、`side`、`quantity`、`contracts`、`price`、`stop_price`、`protective_order`、`trade_id`、`reason`、`realized_pnl`、`fees`、`equity`。不存在的資料應省略，而不是填入不可靠的零值。
