# 審閱歸檔：fleet event log + error request queue + unified safe-halt model (Phase 4a, v0.15.0)

- **PR**：`bcup02/trade-alerts` #17
- **feature 分支**：`feat/phase4a-event-log-and-request-queue`，head `53ea782fea43918b8bfd4cae535c3027a5217fb3`
- **base**：`main` @ `1eab387e3fe4a8e12a406f4fccc9711fed117e6e`
- **squash 合併為**：`d5ceb70`（`gh pr merge --squash --delete-branch` 手動合併，trade-alerts 單分支、無 `scripts/merge-pr.sh`）
- **tag**：`v0.15.0`
- **審閱者**：Perplexity — **結論 `PASS`**（無保留、無後續建議）
- **CI**：`ci / pytest` = success（**161 passed**；baseline 126；+35 新測試）
- **對應 patch**：`20260912-phase4a-event-log-and-request-queue.patch`
- **部署**：無（純函式庫，無部署足跡）

## 背景

「交易機隊錯誤處理重建」8-Phase 計畫的 Phase 4a。Phase 3（PR #15）發布了
`docs/fleet-error-catalog.md` + `catalog/fleet-error-catalog-v1.json`：30 條機隊錯誤條件的
權威分類（R0–R4 風險等級、MECHANICAL/JUDGEMENT 判定）。Phase 4a 把那份目錄所規定的東西
做成可執行的資料結構，供 Phase 4c（三支策略 latch 模型統一）與 Phase 5（修復 bot 影子模式）
使用。目錄裡 `lands_in_phase: 4` 的 13 條就是接下來要改的程式。

## 內容

**1. `safe_halt_model.py`** — 全機隊共用一份 latch 形狀與一套 fingerprint 演算法。
Phase 4c 之前：momentum 用單一 dict、btc-competition 用 4 個扁平欄位、seykota 把
`"SAFE_HALT"` 字串塞在跟 `FLAT`/`LONG` 共用的 `state.status` 欄位裡（這也是 2026-09-11
venv 競態事故當時只能手改 state 檔的原因）、my-crypto 完全沒有 latch。三支 resume 工具算出
三種不同的 fingerprint，而且只有 momentum 的解除對帳本冪等。

兩個刻意偏離 Phase 3 §4.2 初版設計的決定（已寫進 `docs/fleet-error-catalog.md` §4.2）：

- **fingerprint 不再存進 state**。初版照 btc 現行做法存欄位，但存下來的副本會跟它聲稱描述的
  latch 不一致（btc 現行就是這個形狀），確認閘門就形同虛設。改成從 latch 動態算，每個讀取端
  算出來必然一致。
- **新增 `details`，與 `evidence` 分工明確**。`evidence` 是穩定事實、且是 fingerprint 的唯一
  輸入（連同 `code`/`reason`）；`details` 是每輪重新斷言同一個 latch 時會變的診斷資訊。混在
  一起會讓 confirmation token 每輪跳動，preview 印出的 token 在操作者貼回來之前就過期——latch
  會變成永遠無法解除。momentum 現行是靠 `_halt_fingerprint()` 裡一份手維護的排除清單處理同一個
  問題；在寫入端就分開，是把這一整類 bug 消掉而不是繼續逐一列舉它的實例。

另外解決了已發布目錄的一處內部矛盾：§4.2 的範例把存進 state 的 code 寫成帶專案前綴
（`SEY.PROTECTION_UNVERIFIED`），但同一份文件 §5 的命名規則說策略端發出的是不帶前綴的條件名。
以 §5 為準（state 檔逐專案分開，前綴在寫入端多餘），且 `build_safe_halt()` 現在會直接拒絕
帶點的 code，所以同一個條件不會因為寫入的層不同而有兩種拼法。

**2. `fleet_event_log.py`** — append-only JSONL 事件日誌，逐專案一個檔，放策略的 `audit/`。
形狀與鎖定機制照既有的 `projection_outbox.py`（附加時 `flock` 獨佔、解鎖前 `fsync`、讀取時
共享鎖）。這個模組不通知任何人、也不決定風險等級——判準是「57 條錯誤路徑裡 25 條不給人任何
能做得不一樣的決定」。`measurements` 欄位收「只是指標」的數值（`reconciliation_delta` 每筆
都寫、什麼都不升級）。另含 `catalog_code()` / `catalog_entry()` / `risk_tier_for()` 讓呼叫端
把不帶前綴的條件名 join 回目錄。讀到壞行時直接拋錯、不跳過（這個檔案是證據，靜默丟掉一部分
會讓稽核看起來完整而其實不是）。

**3. `error_request_queue.py`** — 跨過門檻的錯誤開一張「請求」（請求對錯誤，就像 PR 對
commit）。開請求仍然不通知。R0 永遠不能開請求，這條寫在函式裡而不是留給呼叫端自律。去重鍵是
`(project, code, evidence)` 的 fingerprint。已關閉的請求拒絕再關。佇列放 `audit/`，刻意
**不放** `/var/lib/*-control`（後者 2770 setgid、ops-control 可寫，放那裡等於讓 Telegram
relay 能偽造待處理項目給修復 bot 去執行）。

兩份新 schema：`schemas/fleet-event-log-v1.schema.json`、
`schemas/error-request-queue-v1.schema.json`。

**刻意不做**：`catalog/fleet-error-catalog-v1.json` 維持是 repository 資料而非 package data，
`load_error_catalog()` 要呼叫端給明確路徑。要讓它可 import 就得搬動 Phase 3 剛發布的檔案位置、
或留第二份會 drift 的副本，兩者都比「呼叫端給路徑」差；留給真正需要部署期查表的那個 Phase。

## 測試

161 passed（126 → 161，+35：11 條 safe_halt_model、13 條 error_request_queue、
11 條 fleet_event_log）。其中三條是會讀**已發布目錄**的硬性不變式：

| 測試 | 不變式 |
|---|---|
| `test_prefix_table_reproduces_every_published_catalog_code` | `PROJECT_CODE_PREFIXES` 必須能重現每一條已發布的 `code`，且其 key 集合等於目錄的 `projects` |
| `test_every_catalog_resume_path_is_one_this_model_implements` | 目錄不得規定任何策略實作不出來的 resume 路徑 |
| `test_r0_conditions_can_never_open_a_request` | 逐筆拿目錄裡每一條 R0 entry 去試開請求，必須全部被拒 |

## Perplexity 審閱結論（PASS，無保留）

逐項獨立驗證（讀到三個新模組的完整原始碼，非截斷 diff）：

1. **fingerprint 穩定性**：`_fingerprint_core()` 只取 `code`/`reason`/`evidence`，`since` 與
   `details` 完全不進雜湊輸入；`re_assert()` 用 fingerprint 而非只比 code 判斷「同一個 latch」。
2. **`check_confirmation()` 邊界**：`(token or "").strip() != expected` 同時擋住 `None`、
   前後空白、舊 token、別的 latch 的 token。
3. **帳本冪等**：`cleared_fingerprints()` 只認 `event_type == "safe_halt_cleared"` 且帶
   `halt_fingerprint` 字串的列，非 mapping 的髒資料 `continue` 跳過不拋例外。
4. **`active_safe_halt()` 邊界**：`{}`、`None`、`{"active": false}`、字串 `"SAFE_HALT"`、
   seykota 舊格式 `{"status": "SAFE_HALT"}` 五種輸入全部讀成「未 latch」，且沒有任何路徑會
   拋例外。Perplexity 特別指出這條的方向是對的：**只有「格式不合法/不完整」的輸入才會讀成
   未 latch，沒有一種「真正在 latch 的合法資料」會被誤判**，符合安全側犯錯的設計。
5. **R0 不得開請求**：確認測試真的從 catalog JSON 讀出 9 條 R0 entry 逐筆試開（不是硬編清單），
   且 `REQUESTABLE_TIERS` 用 frozenset 推導、不受 `RISK_TIERS` 順序影響。
6. **並行安全**：確認 `exclusive_log_lock()` 鎖的是 sibling `.lock` 檔而 `append_jsonl()` 對主
   log 檔另開 fd——兩個不同檔案、不同 fd，不會自己等自己；並確認
   `test_appending_inside_the_shared_lock_does_not_wait_on_itself` **不是假陽性**（若鎖在同一個
   檔案上，這條測試會真的卡住）。
7. **例外型別一致性**：`_require_canonical()` 在 request 與 outcome 兩條路徑都在進鎖與寫入之前
   呼叫，被拒絕的寫入不留半行（多條測試斷言 `not path.exists()`）。
8. **前綴表 drift 防護**：確認測試真的迭代 30 筆真實 catalog entry 反查。
9. **隔離**：三支新模組的 import 只有標準庫（`fcntl`/`json`/`os`/`hashlib`/`contextlib`/
   `datetime`/`pathlib`/`typing`/`uuid`），無 `requests`、無交易所 client、無網路。
   `__init__.py` 的 diff 逐行核對過，既有 `__all__` 條目全部保留、只有新增，`-1` 只是版號那行。
10. **回歸**：新增測試檔計數逐一數過 13+10+12=35，與 CI「126→161（+35）」精確吻合；既有測試檔
    一行未改。

**額外正面發現**（Perplexity 主動提出）：本 PR 也修掉了它在 #15 審閱時記錄的一處未解懸念——
§4.2 範例的 code 從帶前綴改成不帶前綴，並在 `build_safe_halt()` 直接拒絕帶點的 code。

**隔離聲明**：僅讀取 GitHub PR 內容，未接觸 `/opt` `/etc` `/var/lib`、systemd、交易所、
Google、實機帳本。
