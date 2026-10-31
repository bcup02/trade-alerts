# 審閱歸檔：PR #329 觀察區 competition-paxg 檢查

- PR：bcup02/trade-alerts #329，squash 63cbdaf3e163caa465f29a1918f02308ca47a039
- 審閱者：ChatGPT。首審 head 764927af → BLOCK；複審 head 273a19be → PASS。
- BLOCK 原因：新檢查沿用 `_trades_after()`，該函式把缺少 `execution_mode` 的列預設為 LIVE，缺模式證據的 PAXGUSDT 成交會被當真實成交而 OBSERVED。
- 修正：只在 `check_competition_paxg` 要求 `execution_mode == "LIVE"`，不改共用函式；既有「保持 WAITING」測試加一列缺欄位成交。
- CI：run 41205638476，1580 passed。
- 教訓：沿用既有篩選函式時，先看它的預設值是否符合新檢查「要明確證據」的契約。
- 部署：只換開發機偵測單檔 `scripts/observation_watch.py`；不上 A1、不發 tag。
