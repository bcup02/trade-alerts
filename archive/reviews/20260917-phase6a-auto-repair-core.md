# 審閱歸檔：Phase 6a auto-repair core (assess + atomic batch append + audit_notice)

- **PR**：`bcup02/trade-alerts` #21
- **feature 分支**：`feature/phase6a-auto-repair-core`，最終 head `9e94c9f9b09b6bf13f29a7e8f3afdee1b589b60d`（首審 head `6f6555f09408250df6a649a79d22c9a395d233da`）
- **base**：`main` @ `d3168e7`
- **squash 合併為**：`96c3e41`（`gh pr merge --squash --delete-branch`），tag `v0.17.0`
- **審閱者**：Perplexity — 首審 **`BLOCK`** → 複審 **`PASS`**（兩輪）
- **CI**：`pytest` = success（首審 run `35184855364`，195 passed；複審 run `35186469531`，205 passed；baseline 169）
- **對應 patch**：`20260917-phase6a-auto-repair-core.patch`
- **部署**：不需要（純函式庫；version 0.16.0 → 0.17.0）
- **計畫檔**：`~/.claude/plans/phase6-luminous-wave.md`

## 背景

8-Phase 錯誤處理重建的 Phase 6（風險分級 + 低風險自動執行），計畫自評為全專案風險最高的一關（無人看管寫真實損益）。
Phase 5 修復 bot 影子模式已於 2026-09-17 上真倉，但**至今零次觸發**（dev 與真倉的 `fleet_event_log.jsonl` 都不存在），
所以使用者拍板：以 dev 沙盒注入建立正確性證據、真倉續觀察；通知語意採 R2 + 事後稽核通知；範圍只做 momentum
（long-only），seykota 維持影子模式。6a 是第一個子階段：共用核心，本身不會讓任何東西自動寫帳本。

## 這一支做了什麼

1. `assess_auto_repair()`：「完全無歧義」的唯一判定點，無法判斷一律是 blocker、不拋例外。
2. 容忍值比「本地 gross_pnl vs 交易所 realized_pnl」殘差，**不是** `reconciliation_delta`——後者實測恆等於
   `-(entry_fee+exit_fee)`（fixture 為 -0.489 USDT），照原計畫字面實作會擋掉每一筆真實修復。開發中發現並修正計畫。
3. `incident_traces()`：抓只留下 evidence_recorded + fill 的半套修復（既有終端事件檢查看不到）。
4. `atomic_ledger_append`：整批一次 locked write+fsync + read-back 驗證；行內容由呼叫端自己的 TradeLedger staging 產生；刻意不回捲。
5. `build_evidence` 每筆 deal 加 `time_ms`（additive）。
6. `append_repair_from_evidence()`；既有 `append_repair()` 改委派，行為逐位元不變（有對照測試）。
7. 錯誤目錄 risk_tiers 新增 `audit_notice`（只 R2），docs §2.1 區分事後稽核通知與決策請求通知；既有治理不變式一字未改，加兩條新不變式。

開發中抓到的真實缺陷：帳本斷尾（無換行結尾）時直接 append 會把新批次第一筆黏進斷行；已修為先補換行。

## 審閱過程

**首審 BLOCK**：`traces = incident_traces(...) if incident_id else []` 在 incident_id 為空字串／None 時靜默跳過痕跡檢查，
違反函式自己「無法判斷即 blocker」的原則；另 `elif not open_epoch_ms` 分支與 incident_id 缺失分支無獨立測試。
首審同時確認：容忍值方向論證成立（接續 Phase 4e 已驗證事實鏈）、原子性主張誠實、向後相容、audit_notice 不變式守得住。
非阻擋建議：殘差大額邊界測試、併發假陰性文件化、fsync 注入測試命名精確化。

**修正（commit 9e94c9f）**：缺 trade_id／incident_id 本身即 blocker；新增同 trade_id 下其他 incident_id 修復紀錄也擋下
（`other_repair_trace_count`）；補 7 組測試（含參數化）；非阻擋建議三項全數落地。非假陽性佐證：以首審版程式碼跑新測試 4 條紅。

**複審 PASS**：確認漏洞補上、新測試命中對應分支且不被其他 blocker 掩蓋、首審 PASS 項目無回歸、隔離良好。

## 遺留非阻擋觀察（留給 6b）

- `assess_auto_repair` 內 `trade_traces` 比對用 `event.get("trade_id") == trade_id`，未像同段 `_existing_close`／`incident_traces` 做 `str()` 轉型。
  現況 trade_id 全為字串不可觸發，屬一致性瑕疵，6b 動到 trade-alerts 時一併補 `str()` 與型別不一致測試。

## 隔離聲明

未接觸 `/opt` `/etc` `/var/lib`、systemd、交易所、Google、實機帳本；無 token/密鑰；未觸發部署。
