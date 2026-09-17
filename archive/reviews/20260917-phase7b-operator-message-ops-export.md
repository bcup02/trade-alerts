# 審閱歸檔：Phase 7b operator_message + ops_export（trade-alerts 部分）

- **PR**：`bcup02/trade-alerts` #25
- **feature 分支**：`feature/phase7b-operator-message-ops-export`，head `ece070a0425772b8e4788e1bc718b652d73459d0`
- **base**：`main` @ `72dcd06`
- **squash 合併為**：`9676ca6`，tag `v0.18.0`
- **審閱者**：Perplexity — 首審 **`PASS`**（一輪）
- **CI**：`pytest` = success（run `35232062067`；229 passed，baseline 206）
- **對應 patch**：`20260917-phase7b-operator-message-ops-export.patch`
- **部署**：不需要（純函式庫 + 目錄資料；version 0.17.1 → 0.18.0）
- **搭配**：Phase 7b 三個 PR 的第一個；接著 momentum（寫 `audit/ops_export.json`，pin v0.18.0）→ ops-notify（讀匯出檔代送）

## 這一支做了什麼

要修的缺口：momentum 修復 bot 的通知在兩台主機都被靜默丟棄（策略 env 依方針維持 `ALERTS_ENABLED=false`）。
7b 改成策略把快照寫進自己的 `audit/`，由擁有維運頻道的 ops-notify 代送。

1. 錯誤目錄改為 package data（`catalog/` → `src/trade_alerts/catalog/` + pyproject package-data）。策略主機非 editable
   從 git tag 安裝，原本 repo 根目錄的檔案不會被裝上——計畫書沒寫到的缺口。`load_error_catalog()` 不帶參數讀套件內那份，
   帶路徑的舊用法不變。已用乾淨 venv 非 editable 安裝驗證。
2. entry 新增可選 `operator_message {what, direction, steps[]}`，先寫 momentum 修復 bot 三條（R1/R2/R4），步驟指向 momentum
   `docs/operations-modes.md`「對帳補列」實際存在的手動流程。新不變式 4 條。
3. 新模組 `ops_export`：`build_ops_export()` → `fleet-ops-export/v1`（notices：近 7 天 R1–R4 事件含完整訊息 text；
   open_requests：未結案請求附白話三段，`handling_started_at` 本版恆 null、7e 寫入）；`write_ops_export()` 原子替換、0644。
   新 schema。

## 審閱過程

**首審 PASS**：七項重點逐項核對——package data 三方一致且無殘留舊路徑（archive 命中屬正確不動）；目錄其餘條目逐字未動、
三條只追加 `operator_message`；篩選邏輯（R0 排除、跨專案排除、時間窗、等級決定順序、critical 只在 R4、已結案請求排除）
皆有對應測試；三條白話文字與修復 bot 實際行為及既有 rationale 無矛盾、未誘導錯誤操作；寫檔原子性與 0644、輸出無機密欄位；
範圍僅宣稱 16 檔；既有三條目錄相關回歸測試純路徑更新、`load_error_catalog(path)` 相容。

## 遺留非阻擋觀察

- 錯誤目錄三條 momentum entry 的 `sources`（`scripts/repair_bot.py:123/143/217`）是行號參照；momentum 端 7b PR 若使這些行位移，
  需要在下一次動到 trade-alerts 目錄時同步更新（v0.17.1 歸檔留下的兩條 rationale 措辭觀察也一併處理）。

## 隔離聲明

未接觸 `/opt` `/etc` `/var/lib`、systemd、交易所、Google、實機帳本；無 token/密鑰；未觸發部署。
