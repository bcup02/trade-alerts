# Trade Alerts 投資人整合契約 v1

**狀態：第一版草案。** 本文件是跨交易專案的公開資料契約；它描述事件推播與投資人查詢所需的資料，不包含任何交易所憑證、聊天平台秘密或下單指令。JSON 的機器時間欄位使用 ISO 8601 UTC，例如 `2026-08-19T08:00:00Z`，以利跨專案排序與計算；LINE／Telegram 面向投資人的文字畫面則必須轉為 **Asia/Taipei（UTC+8）**，格式為 `年-月-日 時:分`，例如 `2026-08-19 16:00`。

## 1. 設計目標與安全界線

每個交易專案以唯一的 `project_id` 識別自己，透過 `trade-alerts` 發送標準化事件，並提供唯讀的投資人狀態快照。契約的使用者是投資人，因此資料必須能回答「目前是否開倉」、「是否有保護單」、「目前總損益」、「每筆已平倉損益」及「7D、30D、今年、1 年損益」。

契約只允許**通知與唯讀查詢**。`trade-alerts` 不得因通知失敗改變策略決策，也不得透過此契約執行任意 shell、修改秘密、轉帳、下單、解除保護單或啟用實盤。交易專案仍負責風控與交易模式閘門；每一份事件與快照都必須明確帶有 `execution_mode`，而 `DRY_RUN` 是目前唯一允許的模擬測試值。

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

標準 `event_type` 包括 `SYSTEM_HEALTH`, `ENTRY`, `ADD`, `EXIT`, `PROTECTIVE_ORDER_UPDATED`, `ENTRY_SKIPPED`, `PNL_UPDATE`, `SAFE_HALT`, `ERROR` 與 `TEST`。策略可以使用專案前綴的特有事件，但必須保留通用 envelope。

交易事件的 `data` 建議使用：`symbol`、`market`、`timeframe`、`side`、`quantity`、`contracts`、`price`、`stop_price`、`protective_order`、`trade_id`、`reason`、`realized_pnl`、`fees`、`equity`。不存在的資料應省略，而不是填入不可靠的零值。

## 4. 唯讀投資人狀態快照

查詢介面回傳 `portfolio_snapshot` object。它不是交易所帳戶真實餘額的替代品，必須同時提供 `execution_mode` 與 `as_of`。最低欄位如下：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `schema_version` | string | 快照契約版本。 |
| `project_id` / `project_name` | string | 專案識別與顯示名稱。 |
| `execution_mode` | enum | `DRY_RUN`、`PAPER` 或 `LIVE`。 |
| `status` | enum | `HEALTHY`、`FLAT`、`OPEN`、`SAFE_HALT`、`STALE`、`ERROR`。 |
| `as_of` | string | 快照計算時間 UTC。 |
| `last_update_at` | string | 策略資料最後更新時間 UTC。 |
| `equity` | number | 策略所管理的模擬或帳面權益。 |
| `unrealized_pnl` | number | 未實現損益；無法計算時省略並提供 `pnl_status`。 |
| `realized_pnl_total` | number | 已平倉累計損益。 |
| `open_position` | object/null | 目前部位；沒有開倉時為 `null`。 |
| `protective_orders` | array | 目前保護單；沒有保護單時為空陣列。 |
| `performance` | object | `7d`、`30d`、`ytd`、`1y` 四個窗口。 |
| `data_quality` | object | `complete`、`stale`、`missing_fields` 等資料品質資訊。 |

`open_position` 至少包含 `trade_id`（若可用）、`symbol`、`side`、`quantity` 或 `contracts`、`entry_price`、`mark_price`（若可用）、`unrealized_pnl`（若可用）及 `opened_at`。`protective_orders` 至少包含 `order_type`、`side`、`stop_price`、`quantity` 或 `contracts`、`status`；若交易專案只維護策略內部停損，`order_type` 應為 `strategy_stop`，不可聲稱交易所已有委託單。

每個 `performance` 窗口至少包含 `realized_pnl`、`unrealized_pnl_change`（若可計算）、`total_pnl`、`trade_count`、`win_count`、`loss_count`、`calculated_from`。`ytd` 依 UTC 年初起算；若資料不足，仍回傳欄位但以 `null` 表示，並在 `data_quality.missing_fields` 說明原因。

### 策略專屬可選擴充

策略可在 `strategy_extensions.<strategy_id>` 放入不適用於其他專案的唯讀資料；接收端必須容忍未知 extension，其他專案可完全省略。Seykota 使用 `strategy_extensions.seykota` 提供 `protective_stop`（含 `trigger_price`、`status`、`exchange_order`）、`pyramiding`（含 `current_position_add_count` 與 `current_position_total_legs`）及 `loss_streak`（含 `consecutive_closed_losses` 與 `data_complete`）。`loss_streak` 只計算最新一串已平倉且 `realized_pnl < 0` 的模擬交易；只要舊歷史缺少已實現損益，結果必須為 `null` 並標記資料不完整，而不得當成零筆連虧。

## 5. 已平倉交易紀錄

查詢交易紀錄回傳 `closed_trades` 陣列及 `next_cursor`（可選）。每筆至少包含 `trade_id`、`symbol`、`side`、`opened_at`、`closed_at`、`entry_price`、`exit_price`、`quantity` 或 `contracts`、`realized_pnl`、`fees`（若可用）、`close_reason` 與 `execution_mode`。同一 `trade_id` 的加碼應以 `legs` 或 `adds` 保存，不得讓一次交易被重複計入績效。

## 6. 查詢命令對映

LINE／Telegram 介面應提供唯讀命令，名稱可由各專案本地化，但語意固定：`系統狀態` 對映 `status`，`查看投資摘要` 對映 `portfolio_snapshot`，`查看交易紀錄` 對映 `closed_trades`，並新增可選的 `查看損益` 對映 `performance`。所有查詢都必須使用白名單路由與專案 adapter，不得把使用者輸入當作 shell 或檔案路徑執行。文字渲染必須從相同的 `portfolio_snapshot`／`closed_trades` adapter 取得資料，並以 `Asia/Taipei` 顯示人類可讀時間，不可由 LINE 與 Telegram 各自重新解析 state。

## 7. Seykota v1 對映原則

Seykota 的 `BotState.mode` 對映 `execution_mode`，`status` 對映快照 `status`，`position` 對映 `open_position`，`closed_trades` 是逐筆已平倉模擬交易帳本，`equity_history` 是績效窗口的權益基準。新 DRY_RUN 交易會保存 `trade_id`、開／平倉時間、加碼 legs、費用、滑價與已實現損益；開倉持倉會保存最後標記價、策略內部停損與未實現損益。既有歷史 audit 若缺少這些資料，adapter 仍可唯讀顯示，但必須以 `null` 與 `data_quality.missing_fields` 標示，絕不可從文字或缺漏欄位倒推損益。

因此 Seykota adapter 現已支援狀態、開倉、策略內部停損、事件通知、逐筆已平倉損益、累計損益與四個績效窗口。窗口在沒有完整歷史權益基準時會明確標示資料不足；新建的模擬交易與每根已收盤 K 線的權益快照會逐步補齊歷史資料。
