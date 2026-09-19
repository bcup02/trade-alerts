# 審閱歸檔：機隊中英對照表（48 條）＋CI 擋舊叫法＋登記冊補「修復機器人：抓錯並提出修復建議」、動能策略停用開關改已做

- **PR**：`bcup02/trade-alerts` #40，head `27f6b25b5b6c53b2c40246f0969a48192be88c8c`
- **base**：`main` @ `6bc042d`
- **squash 合併為**：`824dd8f`
- **審閱者**：Perplexity — **`PASS（一輪）`**
- **CI**：`pytest` = success（run `35382468952`；287 passed（+6））
- **部署**：不需要（trade-alerts 是純函式庫／資料＋靜態頁；頁面已重新發布到 Artifact）

## 為什麼做

使用者發現同一個東西在各處名稱不同（修復機器人 8 種叫法、真倉同時指主機與真錢等），分不出登記冊與進度頁講的是不是同一個。使用者拍板統一命名，本 PR 只處理 trade-alerts，各策略 repo 列為後續（`docs.glossary_adopted`）。

## 審閱重點

重建動能策略 `scripts/repair_bot.py` 至 `b48b88b` 共 380 行（與 diff 統計算術吻合），確認第 127 行寫提案事件、第 268 行 `if paused: return`、第 374 行讀 `MOMENTUM_REPAIR_PAUSED`；停用開關改已做的判準與 #36 自洽；掃描範圍與排除清單合理；目錄 JSON 只動文字。已知邊界：掃描不含目錄 rationale／auto_action／human_action；`glossary_problems` 不檢查同一英文代號歸到兩個中文名（人工核過無衝突）。

## 隔離聲明

變更只在 trade-alerts 的 `src/trade_alerts/`、`schemas/`、`scripts/`、`tests/`、`docs/` 範圍；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或正式機帳本，無密鑰。完整差異見同名 `.patch`。
