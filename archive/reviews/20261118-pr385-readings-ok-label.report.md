# PR #385 審閱歸檔：維運讀數面板把 RECONCILED／HEALTHY 顯示成 OK

- PR：bcup02/trade-alerts #385；squash `220953a`；審閱 AI：ChatGPT；結論：第 1 輪 PASS（head `ee0986a`，base `fe3368d`，CI run 44261609154，1679 passed）。
- 範圍：`scripts/render_guides.py` 的 `cell()` 只改 chip 顯示字（RECONCILED／HEALTHY → OK），class、嚴重度、過期判斷、tooltip 原始狀態不變；重產一致性登記冊頁面；Node 測試改認 OK。
- 部署：不涉主機；一致性登記冊已重發（版本碼 62c3f9808e1bb13a）。使用者 2026-11-18 決定。

## 已知缺口與後續
1. 過期的 RECONCILED 格仍顯示 OK 字樣（靠 stale 樣式與面板過期警告區分），不能單看字樣判斷資料新鮮。
2. 測試沒逐值驗證 tooltip 仍保留原始值（審閱者建議，非阻擋）。

## 教訓
1. 改顯示字樣時，連測試斷言裡的舊字樣一起找（第一次 CI 因 Node 測試仍斷言舊字樣而失敗）。
