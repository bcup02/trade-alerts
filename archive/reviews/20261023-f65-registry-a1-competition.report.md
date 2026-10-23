# 審閱歸檔 — 登記冊同步競賽 A1 部署（PR #280，f-65／f-64／8b）

- **Repo**：bcup02/trade-alerts
- **PR**：#280，squash 合併為 `44da52597baeef1b44bc4d9229a52fe6388ece6b`；base `d0a5328db40d9799bd8f0f2fff8bb5a98cc6115f`（main）
- **審閱者**：ChatGPT — 首審 BLOCK（head `ef2a1659bd05196c431d20bf0ea0223f50ba5f08`）→ 複審 PASS（head `af12c0147abd7f745d5d49eb569246558c5e8980`），共 2 輪
- **CI**：pytest = success（首審 run `39903880451`、複審 run `39904432866`；皆 1475 passed，無新增測試）

## 做了什麼

競賽 A1 於 2026-10-23 台北 12:55 部署（operations `a8a1ba1` → `6f7457a`，共用庫 0.30.4 → 0.30.19）後，登記冊 `sources.btc-competition.commit` 換到 `6f7457a`；四格改已做：能力 `ledger.capital_flow`、`BTC.EXECUTION_BLOCKED_ZERO_FILLS` 行為格、`FLEET.PROJECTION_TRADE_ID_CONFLICT_PARKED` 行為格與事件日誌格；其餘競賽格引用行號用 `verify_registry_evidence.py --relocate` 搬到同函式內同一行文字（38 筆）；3 筆 `changed` 人工讀過舊新程式後手動改；`recent_changes` 換成四項；兩張頁面重新產生。

## 審閱 BLOCK 與修正

- **首審 BLOCK**：`ledger.capital_flow` 證據寫「`trade_ledger.py:410` 只留可用列、同編號只算一次」，但 `capital_flows_since_anchor()` 實際會回傳未被快照吸收的所有列（含無效列），只是無效列不佔用同編號去重資格；把無效列排除的是下游折算與對帳證據（`capital_flow_delta`）。登記冊把下游過濾行為錯歸給這個函式。修：改成「:410 排除已被快照吸收的列，僅有效列參與同編號去重；無效列在折算時由 capital_flow_delta 跳過」，重新產生頁面。教訓：寫證據句子時，要逐句對到「那一行實際做的事」，不是對到整條路徑最後的效果。
- 審閱者確認三筆手動搬移引用（`runner.py:423／914／630`）、其餘三個新已做格的主要證據、`limit` 如實、`recent_changes` 格式都成立。

## 發布與觀察區

- 合併後重發兩張登記冊（風險登記冊 Version 53、一致性登記冊 Version 72）。
- 觀察區 `registry-awaits`、`registry-drift` 在開發機重跑一輪後回到「等待中」（登記冊沒有等部署的格子；引用的 113 個檔案在 A1 部署複本上與 sources 提交相同）。

## 限制與隔離聲明

審閱者標明界限：沒有登入 A1 重新核實部署與服務狀態（以 PR 提供的部署證據為準）；沒有本地 checkout、沒有重跑 pytest（以 CI 原始日誌為準）；本輪 PASS 不授權任何 A1 實機操作。審閱者只讀 GitHub 的 PR、JSON、來源 commit 與 CI 日誌；沒有接觸 /opt、/etc、/var/lib、systemd、交易所、Google、任何實機 state 或帳本。開發端：只動登記冊資料與產生頁面。
