# 審閱歸檔：錯誤目錄 sources 行號 + AUTO_REPAIRED rationale 補充（Phase 7b 配套，v0.18.1）

- **PR**：`bcup02/trade-alerts` #27，head `7fed2fad1b349b29c00a5e1fcb74da6b6fbdc61f`
- **base**：`main` @ `0f303ec`
- **squash 合併為**：`3c90320`，tag `v0.18.1`
- **審閱者**：Perplexity — 首審 **`PASS`**（一輪，附一項請開發端人工核對的保留）
- **CI**：`pytest` = success（run `35237736998`；229 passed，無新增測試）
- **部署**：不需要（純目錄資料，程式碼零變更；momentum 維持 v0.18.0）

## 這一支做了什麼

1. 三條 `MOM.VERIFIED_CLOSE_*` 的 `sources` 跟上 momentum #90 的行號位移（PROPOSED :123→:128、REPAIR_BLOCKED :143→:153、
   AUTO_REPAIRED :217→:228）。momentum #90 描述寫的 127/152/227 漏算一行新增 import，本 PR 以 grep 為準。
2. 補 v0.17.1 歸檔留下的兩條措辭觀察（AUTO_REPAIRED rationale）：清單加「缺 trade_id／incident_id 等」；抓證據階段靜默中止
   補上 `build_repair_events` 拋 `VerifiedCloseError` 的情況。

## 審閱過程

**首審 PASS**：以 momentum #90 的 unified diff 程式化重算行號，三個新行號全數吻合，且確認 REPAIR_BLOCKED 取的是
`append_fleet_event` 那次（:153）而非 `open_error_request` 那次（:141），與 v0.17.1 取行慣例一致；目錄其餘內容逐字未變。

**保留項與人工核對結果**：審閱工具的 code search 索引查不到 momentum `scripts/repair_bot.py`，無法獨立驗證 VerifiedCloseError
分支的行為描述。開發端直接以 `git show 44524e0:scripts/repair_bot.py` 核對：:310-314 `build_repair_events` 拋
`VerifiedCloseError` 時只 `result["no_evidence"].append(...)` 後 `continue`，不記事件、不呼叫 publish；因為沒有任何
`_HANDLED_CODES` 事件被記下，`_already_handled()`（:99-105）下一輪回傳 False，會重試。rationale 描述正確。

## 隔離聲明

未接觸 `/opt` `/etc` `/var/lib`、systemd、交易所、Google、實機帳本；無 token/密鑰；未觸發部署。
