# 審閱歸檔：Phase 6b catalog entries + str() trade_id checks

- **PR**：`bcup02/trade-alerts` #23
- **feature 分支**：`feature/phase6b-catalog-entries`，最終 head `4fb55bf2b90e3ada9ddc1965d2ab094df74edfc5`（首審 head `0b568b1fe28cd0700b6d20c11c863ba2dc20269c`）
- **base**：`main` @ `2049e6a`
- **squash 合併為**：`d542829`，tag `v0.17.1`
- **審閱者**：Perplexity — 首審 **`BLOCK`** → 複審 **`PASS`**（兩輪；兩輪都交叉核對 momentum PR #88 head `ceb89ea` 的 `scripts/repair_bot.py`）
- **CI**：`pytest` = success（首審 run `35194814639`、複審 run `35196564623`；206 passed，baseline 205）
- **對應 patch**：`20260917-phase6b-catalog-entries.patch`
- **部署**：不需要（純函式庫 + 目錄資料；version 0.17.0 → 0.17.1）
- **搭配**：AI-for-column/mexc-4h-momentum-trailing-stop PR #88（Phase 6b momentum 自動修復），該 PR pin 改為 v0.17.1

## 這一支做了什麼

1. 錯誤目錄 30 → 33 條，sources 指向 momentum #88 `scripts/repair_bot.py`：
   `MOM.VERIFIED_CLOSE_AUTO_REPAIRED`（MECHANICAL／R2／P6，:217）、`MOM.VERIFIED_CLOSE_PROPOSED`
   （JUDGEMENT／R1／P5，補登 Phase 5 既有行為，:123）、`MOM.VERIFIED_CLOSE_REPAIR_BLOCKED`（JUDGEMENT／R4／P6，:143）。
   `docs/fleet-error-catalog.md` §3 計數與 §3.2 表同步。
2. `assess_auto_repair` 內兩處 trade_id 比對補 `str()`（#21 複審遺留觀察），新測試以 v0.17.0 程式碼跑會紅。

## 審閱過程

**首審 BLOCK**：AUTO_REPAIRED 的 rationale 寫「任何一條判準不成立都退回 PROPOSED」，但 #88 `run()` 在帳本已有修復痕跡時走
`_block()` 進 REPAIR_BLOCKED（R4，critical）。權威分級資料對安全關鍵分流描述不準確，只讀目錄的維運人員會低估急迫性。
首審確認其餘項目通過：分級、sources 呼叫內容、文件計數（MECHANICAL = R0+R2、JUDGEMENT = R1+R3+R4 自洽）、str() 修正完整性、不變式、隔離。

**修正（commit 4fb55bf）**：rationale 改寫為列出全部分流（開關關閉 → PROPOSED；痕跡 → REPAIR_BLOCKED；其餘判準不成立 → PROPOSED 附原因；
整批寫入失敗 → REPAIR_BLOCKED；交易所仍有部位 → 抓證據階段中止、不通知）。修正時自行抓到並避免一個新錯：「交易所未確認無部位」
原本差點歸入 PROPOSED，但實際在 fetch 階段 Abort、不進 assess、不通知。另確認 sources 行號（首審懷疑各差 1）在 #88 head 以 grep 直接驗證無誤。

**複審 PASS**：五條分流逐條對得上程式碼、三條條目互相相容、改動只限 rationale 與 runbook、無回歸。

## 遺留非阻擋觀察

- AUTO_REPAIRED rationale 的「其餘判準不成立」清單未窮舉（未列 trade_id／incident_id 缺失、已有 trade_close），且沒加「等」字，讀起來像窮舉。
- `build_repair_events` 因證據結構錯誤拋 `VerifiedCloseError` 時，跟「仍有部位」一樣在抓證據階段靜默中止（`no_evidence`），rationale 只點名後者。

兩者皆不與程式碼矛盾；目錄 JSON 不屬純文件豁免範圍，留待下次動到 trade-alerts 目錄時一併補一句。

## 隔離聲明

未接觸 `/opt` `/etc` `/var/lib`、systemd、交易所、Google、實機帳本；無 token/密鑰；未觸發部署。
