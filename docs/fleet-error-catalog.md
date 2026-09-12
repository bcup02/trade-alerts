# 交易機隊錯誤目錄 v1

**狀態：Phase 3 產出，2026-09-12 定版。** 本文件是全機隊錯誤分類的權威來源；機器可讀版本在
[`catalog/fleet-error-catalog-v1.json`](../catalog/fleet-error-catalog-v1.json)，其形狀由
[`schemas/fleet-error-catalog-v1.schema.json`](../schemas/fleet-error-catalog-v1.schema.json)
定義，不變式由 `tests/test_fleet_error_catalog.py` 守住。兩份內容不一致時，以 JSON 為準——
它是 Phase 4 事件日誌與錯誤處理請求佇列的輸入。

放在 `trade-alerts` 的理由：四支策略與 ops-notify 都已相依這個套件，錯誤碼需要一個所有消費者
都看得到、而且有版本標籤可以釘選的落點。本套件目前沒有任何執行期程式碼讀取這份目錄——它是資料
與契約，不是功能。

---

## 1. 判準

貫穿全專案的唯一問題：

> **這個錯誤讓人做出什麼、跟自動處理不一樣的決定？**

答案是「沒有」→ 它不是錯誤，是一行日誌（`MECHANICAL`）。
答案是具體的某個決定 → 它進錯誤目錄，分風險等級（`JUDGEMENT`）。

這個判準是使用者在盤查 `reconciliation_delta` 時定下的：交易所是權威資料，本地帳本與它不一致
的解法**永遠**是「以交易所為準」，把一個結論早已固定的差異包裝成錯誤→通知→人工處理，不產生
任何決策，只產生疲勞。盤查後推廣到全機隊。

`tests/test_fleet_error_catalog.py::test_mechanical_verdicts_never_reach_a_notifying_tier`
把這條判準寫成了可執行的不變式：`MECHANICAL` 的條目不得落在任何會通知人的風險等級。

## 2. 風險等級

| 等級 | 代號 | 通知 | 自動執行 | 說明 |
|---|---|---|---|---|
| R0 | `LOG` | ✗ | ✗ | 只進事件日誌。偵測之後的動作是固定的。 |
| R1 | `PROPOSE` | ✓ | ✗ | **算出具體解決方案之後**才發 LINE 通知，並把方案當提案附上。絕不無人核准就執行。 |
| R2 | `AUTO_LOW` | ✗ | ✓ | 低風險：直接自動執行，事後記進事件日誌。 |
| R3 | `AUTO_TIMEOUT` | ✓ | ✓ | 中風險：開請求 → Telegram 按鈕可提早核准 → **逾時不按也會執行**。 |
| R4 | `HUMAN_REQUIRED` | ✓ | ✗ | 高風險：持續重複通知直到人處理。永不自動執行。 |

R2 是唯一「自動執行但不通知」的等級，所以 `MECHANICAL` 只能落在 R0 或 R2；反過來，
R1／R3／R4 一律保留給 `JUDGEMENT`。

## 3. 目錄總覽

Phase 2 之後存活、且會產生維運可見訊號的條件共 **30 條**（盤查原始的 57 條路徑裡，6 條是死碼已在
Phase 2c 刪除，其餘多條是同一個條件的重複呼叫點，本目錄以「條件」而非「呼叫點」為單位）。

| 判定 | 條數 | 佔比 |
|---|---|---|
| `MECHANICAL`（動作固定） | 10 | 33% |
| `JUDGEMENT`（真的要人判斷） | 20 | 67% |

| 風險等級 | 條數 |
|---|---|
| R0 日誌 | 9 |
| R1 提案 | 4 |
| R2 自動執行 | 1 |
| R3 逾時自動 | 6 |
| R4 必須人工 | 10 |

### 3.1 ed-seykota（14 條）

| 錯誤碼 | 現況 | 判定 | 等級 | 落在 |
|---|---|---|---|---|
| `SEY.PROTECTION_PLACEMENT_FAILED_FLATTENED` | latch `protective_stop_failed` | MECHANICAL | R2 | P4 |
| `SEY.PROTECTION_PLACEMENT_FAILED_EXPOSED` | latch `protective_stop_failed` | JUDGEMENT | R4 | P4 |
| `SEY.PROTECTION_REPLACE_FAILED` | latch `protective_stop_replace_failed` | JUDGEMENT | R3 | P6 |
| `SEY.PROTECTION_ORPHAN_CANCEL_FAILED` | 通知 only | JUDGEMENT | R1 | P5 |
| `SEY.PROTECTION_CLOSE_CANCEL_FAILED` | 通知 only | JUDGEMENT | R1 | P5 |
| `SEY.PROTECTION_UNVERIFIED` | latch | JUDGEMENT | R4 | P4 |
| `SEY.POSITION_AMBIGUOUS` | latch | JUDGEMENT | R4 | P4 |
| `SEY.RECONCILE_FAILED` | latch | JUDGEMENT | R3 | P4 |
| `SEY.EXCHANGE_TARGET_UNSAFE` | latch | JUDGEMENT | R4 | P4 |
| `SEY.FIXED_IDENTIFIER_CONTRACT_UNAVAILABLE` | latch | JUDGEMENT | R4 | P4 |
| `SEY.RUNTIME_CYCLE_FAILED` | latch（catch-all） | JUDGEMENT | R3 | P4 |
| `SEY.CLOSE_FILL_PENDING` | 誤標 critical | MECHANICAL | R0 | **P3** |
| `SEY.TRADE_EXIT` | 誤標 critical | MECHANICAL | R0 | **P3** |
| `SEY.ENTRY_SKIPPED_MIN_CAPITAL` | 誤標 critical | MECHANICAL | R0 | **P3** |

**`protective_stop_failed` 拆成兩碼**是本節最重要的改動。現行程式在「停損掛單失敗」之後會立刻
嘗試緊急市價平倉，但不論平倉成功或失敗，都收斂成同一個 latch 原因碼。這兩種結果的真倉風險相差
極大：平倉成功代表交易所上沒有任何未保護部位（動作固定 → R2 自動清 latch）；平倉也失敗代表真倉
有裸露部位而且程式的補救手段已經失敗過一次（→ R4，全機隊風險最高的一類）。

### 3.2 momentum（3 條）

| 錯誤碼 | 現況 | 判定 | 等級 | 落在 |
|---|---|---|---|---|
| `MOM.PROTECTION_UNVERIFIED` | latch dict，3 觸發點共用 | JUDGEMENT | R4 | P4 |
| `MOM.STATE_REPAIRED_SAFE_HALT` | 人工工具寫入的 latch | JUDGEMENT | R4 | P4 |
| `MOM.RUNTIME_CYCLE_FAILED` | 不 latch，ERROR heartbeat + 重試 | MECHANICAL | R0 | — |

momentum 是全機隊唯一有完整 latch 模型的實作（dict 欄位 + 原因碼 + 帳本冪等 resume + Telegram
中繼），Phase 4 以它為統一基準，見 §4。它對 catch-all 的處置（`MOM.RUNTIME_CYCLE_FAILED`）也
正是 seykota 要改成的樣子。

### 3.3 btc-competition（4 條）

| 錯誤碼 | 現況 | 判定 | 等級 | 落在 |
|---|---|---|---|---|
| `BTC.BOOK_CORRUPT_NEGATIVE_BALANCE` | latch（4 個扁平欄位） | JUDGEMENT | R4 | P4 |
| `BTC.EXECUTION_BLOCKED_ZERO_FILLS` | latch | JUDGEMENT | R3 | P6 |
| `BTC.REBALANCE_PENDING` | 不 latch，自動續做 | MECHANICAL | R0 | — |
| `BTC.RUNTIME_CYCLE_FAILED` | 不 latch，ERROR heartbeat + 重新拋出 | MECHANICAL | R0 | — |

btc 是唯一已經把「未完成」（`pending_target_weights`）跟「故障」分開的實作，這個區辨在 Phase 4
要推廣到其他三支。

### 3.4 my-crypto（7 條）

| 錯誤碼 | 現行事件名 | 判定 | 等級 | 落在 |
|---|---|---|---|---|
| `MYC.RECONCILE_DELTA_EXCEEDED` | `SAFE_HALT`（誤導） | MECHANICAL | R0 | **P3** |
| `MYC.RUNTIME_CYCLE_FAILED` | `SAFE_HALT`（誤導） | JUDGEMENT | R1 | **P3** 改名 / P5 |
| `MYC.PROTECTION_PLACEMENT_REJECTED` | `PROTECTIVE_STOP_FAILED` | JUDGEMENT | R4 | **P3** 改名 / P5 |
| `MYC.PROTECTION_PLACEMENT_NO_POSITION` | `PROTECTIVE_STOP_FAILED` | JUDGEMENT | R3 | **P3** 改名 / P6 |
| `MYC.PROTECTION_PLACEMENT_ERROR` | `PROTECTIVE_STOP_FAILED` | JUDGEMENT | R4 | **P3** 改名 / P5 |
| `MYC.PROTECTION_REPLACE_FAILED` | `PROTECTIVE_STOP_FAILED` ×2 | JUDGEMENT | R3 | **P3** 改名 / P6 |
| `MYC.PROTECTION_ORPHAN_CANCEL_FAILED` | `PROTECTIVE_STOP_CANCEL_FAILED` | JUDGEMENT | R1 | **P3** 改名 / P5 |

**my-crypto 不加 latch**（使用者 2026-09-12 定案）。兩個叫 `SAFE_HALT` 的事件名宣稱一個這支程式
根本沒有的停機行為——bot 發完通知照常繼續交易。替一支目前沒有這個概念的 LIVE bot 新增停機行為，
風險高於它解決的問題，而且其中一個（`RECONCILE_DELTA_EXCEEDED`）依判準根本不是錯誤。Phase 3 只
改名，讓事件名說實話。

五個共用 `PROTECTIVE_STOP_FAILED` 的呼叫點語意差異很大（明確被拒絕／查不到部位／拋例外／搬移
失敗），風險等級從 R3 到 R4 都有，看 log 的人目前分不出來，Phase 3 一併拆成各自的碼。

### 3.5 跨 repo（2 條）

| 錯誤碼 | 現況 | 判定 | 等級 | 落在 |
|---|---|---|---|---|
| `FLEET.LEDGER_DIVERGED_UNIT_EXIT` | 四支 `exit 2` | MECHANICAL | R0 | P4 |
| `FLEET.GOOGLE_DIVERGED_UNIT_EXIT` | 四支 `exit 3` | MECHANICAL | R0 | P4 |

這 8 條退出碼與 ops-notify 的 `ledger`／`google` 兩軸 LINE 告警**完全重複**：unit 變紅不提供
LINE 以外的任何決策，而且紅 unit 會在下次部署的健康檢查裡製造假訊號（Phase 2a 部署期間實際撞
到過）。Phase 4 把退出碼改回 0，偵測與狀態檔照舊寫出，升級與去抖交給 ops-notify。

## 4. 四支 latch 模型統一（Phase 4 落地規格）

### 4.1 目前的不一致

| 維度 | btc | momentum | seykota | my-crypto |
|---|---|---|---|---|
| latch 型別 | 4 個扁平欄位 | 單一 dict | **字串 `state.status`**（與其他狀態共用欄位） | 無 |
| 原因種類 | 2（自由字串） | 1 個 code，3 觸發點 | 8 種字串、無 code | 無 |
| resume | 本機 CLI | 本機 CLI + Telegram | **無** | N/A |
| resume 帳本冪等 | ✗ | ✓ | N/A | N/A |
| catch-all → latch | ✗ | ✗ | **✓ 唯一一支** | ✗ |

seykota 的 `state.status` 同時裝著 `FLAT`／`LONG`／`SAFE_HALT`，所以「策略停機了」跟「策略目前
空手」共用同一個欄位——這也是 2026-09-11 venv 競態事故當時只能手改 state 檔的原因。

### 4.2 統一後的 latch 記錄

以 momentum 的形狀為基準，四支（my-crypto 除外）採用同一個獨立欄位 `state.safe_halt`：

```json
{
  "active": true,
  "code": "PROTECTION_UNVERIFIED",
  "reason": "交易所存在部位，但沒有可唯一確認的原生保護單",
  "since": "2026-09-12T10:03:00Z",
  "evidence": {"symbol": "BTCUSDT", "side": "long", "quantity": 0.01},
  "details": {}
}
```

權威實作是 `trade_alerts.safe_halt_model`（Phase 4a，v0.15.0）：`build_safe_halt()` 寫出這個
dict，四支共用同一份程式而不是各自複製形狀。與本節初版（Phase 3 定稿）的三處差異，理由如下——

- `code` 取自本目錄，不再是自由字串，但**存的是不帶前綴的條件名**（`PROTECTION_UNVERIFIED`），
  不是目錄碼（`SEY.PROTECTION_UNVERIFIED`）。初版此處的範例與 §5 的命名規則互相矛盾，以 §5
  為準：state 檔本身是逐專案分開的，前綴在寫入端是多餘資訊，讀取端用
  `fleet_event_log.catalog_code(project, code)` 補上。`build_safe_halt()` 會**拒絕**帶點的
  code，所以同一個條件不會因為寫入的層不同而有兩種拼法。
- **`fingerprint` 不再是 state 的欄位。** 初版照 btc 現行做法把它存進 state，但存下來的副本會
  跟它聲稱描述的 latch 不一致（btc 現行就有這個形狀的風險：latch 內容改了、fingerprint 欄位沒
  跟著改，確認閘門就形同虛設）。改由 `safe_halt_fingerprint(halt)` 從 latch 本身動態算，
  每個讀取端算出來必然一致，沒有第二份可以走鐘的副本。
- **新增 `details`，與 `evidence` 分工明確。** `evidence` 是穩定事實，也是 fingerprint 的**唯一**
  輸入（連同 `code`／`reason`）；`details` 是每輪重新斷言同一個 latch 時可能變動的診斷資訊
  （重讀的保護單狀態、當時的標記價、重試次數）。混在一起會讓 fingerprint 每輪跳動，preview
  印出的 token 在操作者貼回來之前就過期——latch 會變成永遠無法解除。momentum 現行是靠
  `_halt_fingerprint()` 裡一份手維護的排除清單處理同一個問題（`updated_at`／
  `protection_status`／`expected_order_id`）；在寫入端就分開，是把這一整類 bug 消掉而不是繼續
  逐一列舉它的實例。
- **`state.status` 不再承載 `SAFE_HALT`**（seykota），部位狀態與停機狀態徹底分家。
- btc 的 4 個扁平欄位（`safe_halt` / `safe_halt_reason` / `safe_halt_fingerprint` /
  `safe_halt_at`）折成同一個 dict。舊 state 檔的遷移：`state.py` 的 `load()` 以
  `k in cls.__dataclass_fields__` 過濾 raw dict，移除的欄位會被靜默忽略，不需要遷移腳本，但
  **一個正在 latch 的舊 state 會在升級時被讀成未 latch**，所以四支的部署前置條件是
  `safe_halt` 為空（比照 Phase 2c/2d 逐支確認 flat/null 的既有慣例）。

### 4.3 統一後的 resume 路徑

全部採用 momentum 現行的兩階段 fingerprint 閘門，它已經在真倉用過。三支共用
`trade_alerts.safe_halt_model` 的同一組函式，各專案只負責讀寫自己的 state 檔與帳本：

1. `resume_preview(halt, events)` 印出目前 latch 的 code、原因、`since`、evidence 與
   confirmation token（＝fingerprint），且保證 `state_file_touched: false`。
2. `check_confirmation(halt, token)`：`resume --confirm <token>` 必須與當下 latch 算出來的
   fingerprint 完全相符才執行——latch 的 evidence 在你讀完 preview 之後變了，舊 token 就失效
   （`details` 變動不會使它失效，見 §4.2）。
3. 解除時往帳本補一筆 `safe_halt_cleared`，欄位由 `safe_halt_cleared_fields()` 產生（三支
   逐欄位一致），並帶上同一個 fingerprint；`assert_not_already_cleared()` 以帳本裡既有的
   `halt_fingerprint` 為準拒絕第二次解除（**帳本冪等**，btc 目前缺這一段，Phase 4 補上）。

seykota 從「無 resume 路徑」直接進到這一套完整閘門。`SEY.EXCHANGE_TARGET_UNSAFE` 與
`SEY.FIXED_IDENTIFIER_CONTRACT_UNAVAILABLE` 兩條是例外（`resume: restart_after_config_fix`）：
它們擋的是設定／憑證層面的錯，改完設定重啟就該重新評估，提供一個「解除」動作反而會讓人誤以為
不改設定也能放行。

### 4.4 catch-all 計數器

`SEY.RUNTIME_CYCLE_FAILED`（`bot.py:1376`）是本專案的核心工作項。改法：

- 未分類例外 → 記事件 + 寫 `DEGRADED` heartbeat + 下一輪重試。
- **連續 N 次（預設 3）** 同類例外才 latch。任何一次成功的循環把計數歸零。
- latch 之後走 §4.3 的 resume 路徑。

其餘八個原因碼在 catch-all 之前就已經各自 latch，不受計數器影響——計數器只作用在「連自己都不知道
是什麼」的那一類。這直接修掉 2026-09-11 venv 競態事故的形狀：一次暫時性的 TLS 憑證讀取失敗，
讓一支真倉策略靜默停止交易且無法遠端復原。

### 4.5 事件日誌（`trade_alerts.fleet_event_log`）

**所有偵測結果都進日誌，而且日誌不通知任何人。** 這是本目錄判準的直接結果：57 條路徑裡 25 條
（44%）不給人任何能做得不一樣的決定，那它們該有的紀錄是一行耐久的資料，不是一則告警。Phase 5
的修復 bot 讀這份日誌來回頭評估自己這段期間的判斷（「看一段時間的決策」取代「看每一筆」）。

- append-only JSONL，逐專案一個檔，放該策略的 `audit/`（跟帳本同一個目錄）。
- 形狀與鎖定機制照 `projection_outbox`：一行一個 JSON 物件、附加時取 `flock` 獨佔鎖、解鎖前
  `fsync`、讀取時取共享鎖。格式在 `schemas/fleet-event-log-v1.schema.json`。
- 因為檔案是逐專案的，`code` 存**不帶前綴的條件名**（同 §4.2）；跨機隊聚合或 join 回本目錄時
  由讀取端用 `catalog_code()` 補前綴。
- `evidence` / `details` 的分工同 §4.2。另有 `measurements` 放「這個條件本身只是一個指標」的
  數值：`reconciliation_delta` **每一筆都寫在這裡、且什麼都不升級**，只有聚合偏離才開請求。
- `risk_tier` 是可選的稽核欄位，記錄寫入當下從本目錄查到的等級。**這個模組自己從不決定等級、
  也從不通知。**
- 讀取時遇到壞行會直接拋錯，不是跳過：這個檔案是證據，靜默丟掉一部分會讓稽核看起來完整而
  其實不是。

### 4.6 錯誤處理請求佇列（`trade_alerts.error_request_queue`）

跨過門檻的錯誤開一張「請求」——請求對錯誤，就像 PR 對 commit：它指名一個條件、帶著證據與本目錄
的風險等級，開著直到有一個 outcome 關掉它。**開請求此時仍然不通知**；Phase 5 的修復 bot 先算出
具體的修復內容，才發通知並附上提案（只重述問題的通知，等於把機器能做的分析丟回給讀的人做）。

- 佇列放策略的 `audit/`，**刻意不放 `/var/lib/*-control`**——後者是 2770 setgid、ops-control
  可寫，放那裡等於讓 Telegram relay 能偽造待處理項目給修復 bot 去執行。
- **R0 永遠不能開請求**，這條規則寫在函式裡而不是留給每個呼叫端自律。R0 的意思是偵測之後的動作
  是固定的，所以沒有東西可以讓一張請求「關於」它——那些只進 §4.5 的事件日誌。這與本目錄
  「MECHANICAL 判定不得落在會通知的等級」是同一條判準的兩個執行點。
- 去重鍵是 `(project, code, evidence)` 的 fingerprint：一個條件連續成立 20 個輪詢週期產生
  **一張**請求，不是 20 張。請求被解決之後同一條件再發生，會開**新的一張**——策略確實第二次撞到
  這個問題，值得一張新請求，而不是靜默重開一張已關閉的。
- 關閉狀態四種：`RESOLVED_AUTO`（R2，以及 R3 逾時後自動執行）、`RESOLVED_HUMAN`、`SUPERSEDED`
  （同條件帶著不同證據重開）、`WITHDRAWN`（條件自己不再成立）。已關閉的請求拒絕再關一次——
  outcome 是「實際發生了什麼」的稽核紀錄，第二筆會讓歷史對「哪個修復真的跑了」變得有歧義。
- 格式在 `schemas/error-request-queue-v1.schema.json`。

## 5. Phase 3 實際落地的程式改動

本 Phase 以設計為主，程式改動限縮在「零風險的標記與命名修正」——不動任何 latch、resume 或交易
決策邏輯：

| repo | 改動 |
|---|---|
| `trade-alerts` | 新增本文件 + catalog JSON + schema + 不變式測試 |
| `ed-seykota-...` | `CLOSE_FILL_PENDING`／`EXIT`／`ENTRY_SKIPPED` 三處 `critical=True` → `False` |
| `my-crypto-bot` | 8 個 `critical=True` 事件名改成目錄碼；兩個誤導性的 `SAFE_HALT` 改成真實語意 |

兩支策略的 dispatcher 目前都是 log-only no-op（`_notify` / `_LogOnlyAlerts`），改動只影響本地
log 行的 `event=` 與 `severity=` 欄位，不影響任何推播、下單或狀態寫入。

**事件名的命名規則**：程式裡發出的事件名用**不帶前綴的條件名**（例如 `PROTECTION_REPLACE_FAILED`），
目錄代碼則是 `<專案前綴>.<條件名>`（`MYC.PROTECTION_REPLACE_FAILED`）。事件來自哪一支策略在
發出的當下一定已知——日誌行、heartbeat、Phase 4 的事件日誌都是逐專案分開的——所以前綴在程式端
是多餘的，join 回目錄只需要「專案 + 事件名」。前綴的用處在跨機隊聚合的場合，屆時由讀取端補上。

## 6. 修改本目錄

- 新增條件：加一筆 entry，`code` 一經發布就不得改指別的條件。
- 改風險等級：連同 `rationale` 一起改，說清楚為什麼判斷變了。
- 每次改動都要跑 `tests/test_fleet_error_catalog.py`；`MECHANICAL` 不得落進會通知的等級這條
  不變式是硬性的，測試擋下來時要改的是判定或等級，不是測試。
- Phase 4a 起另有三條會讀本目錄的不變式，同樣是硬性的：
  `test_fleet_event_log.py::test_prefix_table_reproduces_every_published_catalog_code`
  （`PROJECT_CODE_PREFIXES` 不得與已發布的 `code` 前綴 drift）、
  `test_safe_halt_model.py::test_every_catalog_resume_path_is_one_this_model_implements`
  （entry 不得規定沒有任何策略實作得出來的 resume 路徑）、
  `test_error_request_queue.py::test_r0_conditions_can_never_open_a_request`
  （逐筆拿目錄裡的 R0 條件去試開請求，必須全部被拒）。
