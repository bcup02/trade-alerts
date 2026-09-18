# 交易機隊錯誤目錄 v2

**狀態：Phase 3 產出（2026-09-12 v1 定版），2026-09-18 升 v2（風險分級由五級改四級，見 §2）。** 本文件是全機隊錯誤分類的權威來源；機器可讀版本在
[`src/trade_alerts/catalog/fleet-error-catalog-v2.json`](../src/trade_alerts/catalog/fleet-error-catalog-v2.json)，其形狀由
[`schemas/fleet-error-catalog-v2.schema.json`](../schemas/fleet-error-catalog-v2.schema.json)
定義，不變式由 `tests/test_fleet_error_catalog.py` 守住。兩份內容不一致時，以 JSON 為準——
它是 Phase 4 事件日誌與錯誤處理請求佇列的輸入。

放在 `trade-alerts` 的理由：四支策略與 ops-notify 都已相依這個套件，錯誤碼需要一個所有消費者
都看得到、而且有版本標籤可以釘選的落點。Phase 7b 起這份 JSON 隨套件發佈（package data），
`trade_alerts.ops_export` 在策略主機上執行期讀它的 `operator_message` 組通知文字，見 §4.8。

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

## 2. 風險等級（v2，2026-09-18）

| 等級 | 代號 | 自動處理 | 通知 | 說明 |
|---|---|---|---|---|
| R0 | `LOG` | 不用處理 | 不通知 | 只進事件日誌。偵測之後的動作是固定的。 |
| R1 | `AUTO` | 直接做 | **不通知** | 自動執行並記進事件日誌。沒有第二個選項，告訴人也沒有東西可以決定。 |
| R2 | `RETRY_ESCALATE` | 自動嘗試恢復 | 連續失敗 `escalate_after`（預設 3）次才通知一次 | 系統自己先試；試不起來才升格：開請求、通知，附白話步驟與給 AI 的根因追查指令。 |
| R3 | `HUMAN_REQUIRED` | 絕不自動 | 通知並持續提醒 | 高風險：一定要人處理，提醒到有人處理為止。 |

**排序的軸是「人能不能做出跟自動處理不一樣的決定」，不是事情有多嚴重。** R0／R1 人沒有決定可做
（`MECHANICAL`，永遠不通知）；R2／R3 才會到人手上（`JUDGEMENT`）。`test_mechanical_verdicts_never_reach_a_notifying_tier`
照這條寫成不變式。

### 2.1 v2 改了什麼、為什麼

使用者 2026-09-18 讀風險登記冊後拍板，理由與決定：

- **v1 的 R1「提案、交給人決定」沒有意義。** 交易所是權威資料：治標就是照交易所讓帳本、交易所、
  Google 表三方一致，這件事機器能做就該自己做；真正需要人的只有「機器試了還是對不上」，而那時人要做的
  是追查根因——所以 v2 的升格訊息一律附一段可以直接貼給 AI 的根因追查指令（`operator_message.ai_prompt`）。
- **v1 的 R3「逾時自動執行＋Telegram 提早核准」取消。** 動作內容確定的就立即重試；重試起不來才升格。
  v1 R1 與 v1 R3 合併成 v2 R2。
- **v1 的 R2 事後稽核通知取消**，v1 R2 → v2 R1 不通知。自動補寫帳本只是記下交易所上已經發生的事，
  沒有動到任何錢。`audit_notice` 欄位刪除。
- v1 R4 → v2 R3，內容不變。
- 請求佇列只收 R2（升格時）與 R3；ops-notify 只轉送 R3 與升格的 R2。
- 退役代碼列在 JSON 的 `retired_codes`，永不重用（不變式守住）。
- 條目的 `auto_action`／`human_action` 描述的是 v2 目標行為，落在 `lands_in_phase`（8＝v2 分級落實到各策略）；
  **某支策略實際做到了沒有，不在本目錄，而在全機隊一致性登記冊追蹤。**

## 3. 目錄總覽

Phase 2 之後存活、且會產生維運可見訊號的條件共 **30 條**（Phase 6 另補 3 條 momentum 修復 bot 條件，目前合計 **33 條**）（盤查原始的 57 條路徑裡，6 條是死碼已在
Phase 2c 刪除，其餘多條是同一個條件的重複呼叫點，本目錄以「條件」而非「呼叫點」為單位）。

| 判定 | 條數 | 佔比 |
|---|---|---|
| `MECHANICAL`（動作固定） | 11 | 33% |
| `JUDGEMENT`（真的要人判斷） | 22 | 67% |

| 風險等級（v2） | 條數 |
|---|---|
| R0 只記錄 | 9 |
| R1 自動、不通知 | 2 |
| R2 自動嘗試、失敗才通知 | 11 |
| R3 必須人工 | 11 |

下列各表的「等級」「落在」兩欄以 JSON 為準重新產生（v2）；「現況」欄描述 Phase 3 盤查時的程式行為。

### 3.1 ed-seykota（14 條）

| 錯誤碼 | 現況 | 判定 | 等級 | 落在 |
|---|---|---|---|---|
| `SEY.PROTECTION_PLACEMENT_FAILED_FLATTENED` | latch `protective_stop_failed` | MECHANICAL | R1 | P4 |
| `SEY.PROTECTION_PLACEMENT_FAILED_EXPOSED` | latch `protective_stop_failed` | JUDGEMENT | R3 | P4 |
| `SEY.PROTECTION_REPLACE_FAILED` | latch `protective_stop_replace_failed` | JUDGEMENT | R2 | P8（v2） |
| `SEY.PROTECTION_ORPHAN_CANCEL_FAILED` | 通知 only | JUDGEMENT | R2 | P8（v2） |
| `SEY.PROTECTION_CLOSE_CANCEL_FAILED` | 通知 only | JUDGEMENT | R2 | P8（v2） |
| `SEY.PROTECTION_UNVERIFIED` | latch | JUDGEMENT | R3 | P4 |
| `SEY.POSITION_AMBIGUOUS` | latch | JUDGEMENT | R3 | P4 |
| `SEY.RECONCILE_FAILED` | latch | JUDGEMENT | R2 | P4 |
| `SEY.EXCHANGE_TARGET_UNSAFE` | latch | JUDGEMENT | R3 | P4 |
| `SEY.FIXED_IDENTIFIER_CONTRACT_UNAVAILABLE` | latch | JUDGEMENT | R3 | P4 |
| `SEY.RUNTIME_CYCLE_FAILED` | latch（catch-all） | JUDGEMENT | R2 | P4 |
| `SEY.CLOSE_FILL_PENDING` | 誤標 critical | MECHANICAL | R0 | **P3** |
| `SEY.TRADE_EXIT` | 誤標 critical | MECHANICAL | R0 | **P3** |
| `SEY.ENTRY_SKIPPED_MIN_CAPITAL` | 誤標 critical | MECHANICAL | R0 | **P3** |

**`protective_stop_failed` 拆成兩碼**是本節最重要的改動。現行程式在「停損掛單失敗」之後會立刻
嘗試緊急市價平倉，但不論平倉成功或失敗，都收斂成同一個 latch 原因碼。這兩種結果的真倉風險相差
極大：平倉成功代表交易所上沒有任何未保護部位（動作固定 → R1 自動清 latch）；平倉也失敗代表真倉
有裸露部位而且程式的補救手段已經失敗過一次（→ R3，全機隊風險最高的一類）。

### 3.2 momentum（6 條）

| 錯誤碼 | 現況 | 判定 | 等級 | 落在 |
|---|---|---|---|---|
| `MOM.PROTECTION_UNVERIFIED` | latch dict，3 觸發點共用 | JUDGEMENT | R3 | P4 |
| `MOM.STATE_REPAIRED_SAFE_HALT` | 人工工具寫入的 latch | JUDGEMENT | R3 | P4 |
| `MOM.RUNTIME_CYCLE_FAILED` | 不 latch，ERROR heartbeat + 重試 | MECHANICAL | R0 | — |
| `MOM.VERIFIED_CLOSE_PROPOSED` | 修復 bot 提案通知 | JUDGEMENT | R2 | P8（v2） |
| `MOM.VERIFIED_CLOSE_AUTO_REPAIRED` | 開關開啟 + 無歧義才自動寫帳本，事後稽核通知 | MECHANICAL | R1 | **P6** |
| `MOM.VERIFIED_CLOSE_REPAIR_BLOCKED` | 修復痕跡／寫入失敗 → 停手 critical 一次 | JUDGEMENT | R3 | **P6** |

momentum 是全機隊唯一有完整 latch 模型的實作（dict 欄位 + 原因碼 + 帳本冪等 resume + Telegram
中繼），Phase 4 以它為統一基準，見 §4。它對 catch-all 的處置（`MOM.RUNTIME_CYCLE_FAILED`）也
正是 seykota 要改成的樣子。

後三條是 Phase 6 的 verified-close-backfill 修復 bot（`scripts/repair_bot.py`）。v2 起：無歧義 → R1 自動寫、不通知；
以交易所為準仍能對應 → 照交易所補寫；只有結構上對不上才重試並升格（R2，`MOM.VERIFIED_CLOSE_PROPOSED` 的呼叫點
由共用修復執行器取代時退役）；帳本已不乾淨 → R3 停手。v1 的過渡開關 `MOMENTUM_REPAIR_AUTO_APPLY`（只有 momentum
有、33 條只管 1 條、沒有任何機制會評估並打開它）在 v2 移除；seykota 的影子 bot 發出的
`SEY.VERIFIED_CLOSE_PROPOSED` 從未登記進 v1 目錄，v2 列入 `retired_codes`，seykota 改用同一個共用執行器。

### 3.3 btc-competition（4 條）

| 錯誤碼 | 現況 | 判定 | 等級 | 落在 |
|---|---|---|---|---|
| `BTC.BOOK_CORRUPT_NEGATIVE_BALANCE` | latch（4 個扁平欄位） | JUDGEMENT | R3 | P4 |
| `BTC.EXECUTION_BLOCKED_ZERO_FILLS` | latch | JUDGEMENT | R2 | P8（v2） |
| `BTC.REBALANCE_PENDING` | 不 latch，自動續做 | MECHANICAL | R0 | — |
| `BTC.RUNTIME_CYCLE_FAILED` | 不 latch，ERROR heartbeat + 重新拋出 | MECHANICAL | R0 | — |

btc 是唯一已經把「未完成」（`pending_target_weights`）跟「故障」分開的實作，這個區辨在 Phase 4
要推廣到其他三支。

### 3.4 my-crypto（7 條）

| 錯誤碼 | 現行事件名 | 判定 | 等級 | 落在 |
|---|---|---|---|---|
| `MYC.RECONCILE_DELTA_EXCEEDED` | `SAFE_HALT`（誤導） | MECHANICAL | R0 | **P3** 改名 / **P4e** 定案不聚合 |
| `MYC.RUNTIME_CYCLE_FAILED` | `SAFE_HALT`（誤導） | JUDGEMENT | R2 | P8（v2） |
| `MYC.PROTECTION_PLACEMENT_REJECTED` | `PROTECTIVE_STOP_FAILED` | JUDGEMENT | R3 | **P3** 改名 / P5 |
| `MYC.PROTECTION_PLACEMENT_NO_POSITION` | `PROTECTIVE_STOP_FAILED` | JUDGEMENT | R2 | P8（v2） |
| `MYC.PROTECTION_PLACEMENT_ERROR` | `PROTECTIVE_STOP_FAILED` | JUDGEMENT | R3 | **P3** 改名 / P5 |
| `MYC.PROTECTION_REPLACE_FAILED` | `PROTECTIVE_STOP_FAILED` ×2 | JUDGEMENT | R2 | P8（v2） |
| `MYC.PROTECTION_ORPHAN_CANCEL_FAILED` | `PROTECTIVE_STOP_CANCEL_FAILED` | JUDGEMENT | R2 | P8（v2） |

**my-crypto 不加 latch**（使用者 2026-09-12 定案）。兩個叫 `SAFE_HALT` 的事件名宣稱一個這支程式
根本沒有的停機行為——bot 發完通知照常繼續交易。替一支目前沒有這個概念的 LIVE bot 新增停機行為，
風險高於它解決的問題，而且其中一個（`RECONCILE_DELTA_EXCEEDED`）依判準根本不是錯誤。Phase 3 只
改名，讓事件名說實話。

五個共用 `PROTECTIVE_STOP_FAILED` 的呼叫點語意差異很大（明確被拒絕／查不到部位／拋例外／搬移
失敗），風險等級從 R2 到 R3 都有，看 log 的人目前分不出來，Phase 3 一併拆成各自的碼。

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

### 4.4 連續失敗計數器（2026-09-15 修正：範圍包含兩個原因碼，不是只有 catch-all）

`SEY.RUNTIME_CYCLE_FAILED`（`bot.py` `run_forever` 的 catch-all）是本專案的核心工作項。改法：

- 未分類例外 → 記事件 + 寫 `DEGRADED` heartbeat + 下一輪重試。
- **連續 N 次（預設 3）** 同類例外才 latch。任何一次成功的循環把計數歸零。
- latch 之後走 §4.3 的 resume 路徑。

`SEY.RECONCILE_FAILED`（`bot.py` `reconcile()` 排除暫時性網路錯誤後剩下的例外，主要是解析失敗、
交易所回傳非預期結構）**額外套用同一套計數器邏輯，兩碼各自獨立計數**——這條路徑正是 2026-09-11
venv 競態事故實際 latch 的地方（見 rationale），單次失敗就停真倉策略的代價，跟 catch-all 的論證
完全一樣。**其餘七個**原因碼在這兩處之前就已經各自 latch，不受計數器影響——計數器只作用在「連自己
都不知道是什麼」的 catch-all，以及「多半是一次性、但無法歸類成上面任何一個具體原因碼」的
`RECONCILE_FAILED`。（2026-09-15 之前的版本誤寫成「其餘八個」，把 `RECONCILE_FAILED` 也算進不受
影響的那組——JSON 目錄裡 `SEY.RECONCILE_FAILED` 的 `auto_action` 其實從一開始就寫著計數器語言，
兩處互相矛盾，Phase 4d 開工時拍板以此處修正為準。）

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
  數值：`reconciliation_delta` 寫在這裡、永遠不升級——**2026-09-15（Phase 4e）撤回「聚合偏離
  才開請求」的計畫**，見 §4.7，這個指標永久停在事件日誌這一層，不會有東西讀它去開 §4.6 的請求。
- `risk_tier` 是可選的稽核欄位，記錄寫入當下從本目錄查到的等級。**這個模組自己從不決定等級、
  也從不通知。**
- 讀取時遇到壞行會直接拋錯，不是跳過：這個檔案是證據，靜默丟掉一部分會讓稽核看起來完整而
  其實不是。

### 4.6 錯誤處理請求佇列（`trade_alerts.error_request_queue`）

跨過門檻的錯誤開一張「請求」——請求對錯誤，就像 PR 對 commit：它指名一個條件、帶著證據與本目錄
的風險等級，開著直到有一個 outcome 關掉它。**開請求此時仍然不通知**；Phase 5 的修復 bot 先算出
具體的修復內容；v2 起請求只在需要人時才開（R2 升格、R3），通知附白話步驟與給 AI 的根因追查指令
（只重述問題的通知，等於把機器能做的分析丟回給讀的人做）。

- 佇列放策略的 `audit/`，**刻意不放 `/var/lib/*-control`**——後者是 2770 setgid、ops-control
  可寫，放那裡等於讓 Telegram relay 能偽造待處理項目給修復 bot 去執行。
- **R0／R1 永遠不能開請求**，這條規則寫在函式裡而不是留給每個呼叫端自律。R0 的意思是偵測之後的動作
  是固定的、R1 是已經自動做完，所以沒有東西可以讓一張請求「關於」它——那些只進 §4.5 的事件日誌。這與本目錄
  「MECHANICAL 判定不得落在會通知的等級」是同一條判準的兩個執行點。
- 去重鍵是 `(project, code, evidence)` 的 fingerprint：一個條件連續成立 20 個輪詢週期產生
  **一張**請求，不是 20 張。請求被解決之後同一條件再發生，會開**新的一張**——策略確實第二次撞到
  這個問題，值得一張新請求，而不是靜默重開一張已關閉的。
- 關閉狀態四種：`RESOLVED_AUTO`（升格後的 R2 自動重試終於成功）、`RESOLVED_HUMAN`、`SUPERSEDED`
  （同條件帶著不同證據重開）、`WITHDRAWN`（條件自己不再成立）。已關閉的請求拒絕再關一次——
  outcome 是「實際發生了什麼」的稽核紀錄，第二筆會讓歷史對「哪個修復真的跑了」變得有歧義。
- 格式在 `schemas/error-request-queue-v1.schema.json`。

### 4.8 白話通知文字與維運匯出（Phase 7b，`trade_alerts.ops_export`）

**策略不自己推播，ops-notify 代送。** 策略的 env 維持 `ALERTS_ENABLED=false`（2026-08-30 方針），
所以修復 bot 以前呼叫 `publish` 的通知在兩台主機上其實都被靜默丟掉。Phase 7b 改成：策略把要讓人
知道的事整理成 `audit/ops_export.json`，擁有維運頻道的 ops-notify 讀它、每筆只送一次。

- **`operator_message`**（v2 起**每條 entry 必填**）：`{what, direction, steps[], ai_prompt}`＝發生什麼事、
  解決方向、處理步驟、給 AI 的根因追查指令，語氣比照機隊風險登記冊，不用術語。三段皆不得為空；
  `ai_prompt` 在 R2／R3 必填、R0／R1 不得有。v1 只寫了 3 條、「其餘接入時再補」——這正是 v2 要消除的
  「先做一部分、沒登記」，所以 v2 一次補齊 33 條，風險登記冊頁也由它產生。
- **`build_ops_export(fleet_event_log, request_queue, *, project, catalog=None, window_days=7)`**：
  - `notices`：近 `window_days` 天**需要人**的事件——所有 R3，以及 `details.escalated` 為真的 R2
    （R0／R1 永遠不在內，未升格的 R2 也不在內），以 `event_id` 為鍵讓讀取端每筆只送一次。等級以事件上
    記錄的為準，沒記錄才查目錄。`text` 是完整訊息本體：等級標頭 → 目錄標題 → 白話三段 → 「技術細節」
    （事件 `details.notice_text`，沒有就用 `summary`）→ 給 AI 的追查指令（目錄的 `ai_prompt`＋本次事件的
    錯誤碼、事件編號與 evidence，可整段貼給 AI）。`critical` 恰好在 R3 時為真。格式 `fleet-ops-export/v2`。
  - `open_requests`：所有未結案請求，附目錄的白話三段與 `ai_prompt`；`handling_started_at` 本版恆為
    `null`，Phase 7e 的「開始處理」按鈕才會寫入。
  - 事件日誌或佇列有壞行時直接拋錯（同 §4.5），不輸出一份看起來完整其實缺一塊的匯出；呼叫端
    best-effort 寫檔，匯出停止更新時由 ops-notify 報 `STALE`。
- **`write_ops_export(path, export)`**：整份原子替換、`0644`。檔案由策略自己的服務帳號寫進
  `audit/`；ops-notify／ops-control 只有群組讀權限，relay 端無法偽造要送的項目（與 §4.6 佇列放
  `audit/` 同一個理由）。
- 格式在 `schemas/fleet-ops-export-v2.schema.json`。

### 4.7 `reconciliation_delta`：撤回聚合計畫（Phase 4e，2026-09-15）

§4.5/4.6 原本規劃 `reconciliation_delta` 是請求佇列的第一個生產者：每筆照存不觸發，只有**聚合
偏離**（連續同向 N 筆 / 移動平均偏離零）才開請求。Phase 4e 開工盤查 trading-main 真實帳本後
**撤回這個計畫**——不是實作方式的問題，是這個訊號本身已經不需要聚合邏輯。

**盤查發現**：拉出 momentum 連續 17 筆、my-crypto 唯一 1 筆有效資料的 `reconciliation_delta`，
每一筆都精確等於 `-(entry_fee + exit_fee)`，誤差在小數點第 6 位。原因：交易所回報的
`exchange_profit` 是手續費前的毛損益，本地 `net_pnl` 是手續費後的淨損益，兩者相減從定義上就
只會得到「負的手續費」——不是雜訊，是一個已知、良性、每筆都會出現、方向永遠一致的系統性偏差。
不管怎麼調整比較公式（比毛損益還是想辦法比淨損益），聚合起來永遠是同一個已知原因，不會有真正
需要人介入的訊號可抓。

**為什麼觀察不到殘留雜訊**：這個指標最初想抓的問題（my-crypto 程式碼開頭第 13 點）是「本地記錄
的進出場價格跟交易所現實脫節，錯誤會沿用進未來的移動停損計算」。這個問題已經被 my-crypto
2026-08-22 的另一個修正（第 14 點：`_fetch_order_info()` 改用交易所確認過的
`dealAvgPrice`/`totalFee` 入帳）從源頭堵住了——本地價格現在本來就是交易所確認過的數字，不會再
脫節，所以 `reconciliation_delta` 剩下的就只有手續費這個已知常數，不會再出現代表真實問題的
離群值。

**結論**：`reconciliation_delta` 永久停在 §4.5 事件日誌這一層，**不建聚合邏輯、不接 §4.6 請求
佇列**。my-crypto 端把原本呼叫的 `alerts.publish("RECONCILE_DELTA_EXCEEDED", ...)` 換成
`append_fleet_event(...)`——後者在 my-crypto 本來就已經是 2026-08-30 起的本地 no-op stub（見
`_LogOnlyAlerts`），這次替換是把稽核紀錄放進機隊統一格式，不是關掉一個正在發送的通知。momentum
維持現狀不動（本來就只寫帳本、完全沒有事件產生）。§4.6 的請求佇列基礎設施留著，等以後真的出現
需要它的訊號源再用。

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
  `test_error_request_queue.py::test_r0_and_r1_conditions_can_never_open_a_request`
  （逐筆拿目錄裡的 R0／R1 條件去試開請求，必須全部被拒）。
- v2 起的白話文字與分級不變式：每條都有 `operator_message` 且三段皆非空、R2／R3 必有 `ai_prompt`
  而 R0／R1 不得有、四級語意固定、只有 R2 帶 `escalate_after`、退役代碼不得重用。改通知文字就是改這份
  JSON——它隨套件發佈，策略重新釘選新版本才會生效。
