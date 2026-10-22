# 審閱歸檔：f-45 維運健康表打包、簽章與黃金請求（PR #265）

- PR：bcup02/trade-alerts #265；squash `3b8322c`（main）；tag `v0.30.16`
- 首審 head `452fc6b3c9d1bb11a3e8603e3b44a535cdc10b67`（BLOCK）；複審 head `c1aa5c0d96fcf7b09b46a7dda40d160be8f64428`（PASS）；base `8d6100ab3c183f4e721fea5ead4f9d95135a1853`
- 審閱：2 輪（ChatGPT）。首審 BLOCK、複審 PASS。CI：首審 run 39724213476（1230 passed，基線 1212，+18）；複審 run 39724859734（1258 passed，+28 負測試）。

## 重點
- 新增 `trade_alerts.fleet_health`（純函式）：健康表建立與驗證、gzip＋base64 決定性打包（上限 9000，同接收端）、儲存格文字 `HEALTHv1|…|HEALTHEND` 與解析、`put_health_v1` 簽章請求。黃金請求檔讓 Python 與真正的 `google_ledger_receiver.gs` 對同一份位元組驗簽。
- 首審 BLOCK 兩點，皆成立：①表格只驗 schema 名稱，缺欄／空 readings 的損壞表格仍能 encode／decode；②簽章請求只驗時間非空、`sheet_name` 完全不驗，會簽出接收端必拒絕的請求。
- 修法：`validate_health_table`（四成員、兩個帶時區 ISO、非空 readings、每列恰好五個非空字串欄；encode 前與 decode 後都驗）；`signed_health_request` 時間改嚴格 ISO、可傳 `now` 擋超過 5 分鐘、移除 `sheet_name` 參數固定「維運健康」。

## 限制（給後續 PR）
- 沒傳 `now` 時只驗時間格式、不驗是否過期。**ops-notify 發布單元必須傳入帶時區的當前時間**（審閱者列為後續 PR 審閱清單）。
- 嚴格 ISO 比 JavaScript `Date` 窄（刻意 fail-closed）；沒有逐一用 JavaScript 比對兩者接受域。

## 部署
- 純新增模組、沒有呼叫端；不部署。A1 與開發機未動。

## 隔離聲明
審閱端只讀 GitHub 程式碼、提交差異與 CI 日誌；未碰 /opt、/etc、/var/lib、systemd、交易所、Google 或 A1；未 checkout、未 push。
