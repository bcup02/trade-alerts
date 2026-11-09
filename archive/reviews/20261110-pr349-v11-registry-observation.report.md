# PR #349 審閱歸檔：V11 登記冊預定關卡改成開發機演練、觀察區新增 dev-v11-cycle（v0.30.29，進度頁 1.5d5）

- PR：bcup02/trade-alerts #349；squash `aef6f8c`；tag `v0.30.29`；審閱 AI：ChatGPT；結論：首審 BLOCK（349-01）→ 複審 PASS（head `8ddf06d7`，CI run 42634311990，1614 passed）
- 範圍：①登記冊 V11 專案 119 格預定關卡由 `v11-5d` 改成 `v11-p3`／`v11-google-reconcile`，理由改寫、`recent_changes` 74 筆 updated；②觀察區 `scripts/observation_watch.py` 新增檢查 `dev-v11-cycle`（讀開發機 /opt/trend-meteor 的狀態、心跳、帳本、對帳狀態；對應進度頁 phase-v10-p3），含 18 個測試；③錯誤目錄說明、兩張登記冊重新產生、pyproject 0.30.29。
- 審閱 349-01：對帳狀態檔、帳本尚未產生時應視為等待而不是檢查錯誤（避免 `consecutive_errors` 累積成誤通知）；修正為 `RemoteFileMissing` 轉 WAITING，補 4 個測試（缺檔、五輪不累積、權限不足仍為 ERROR、檔案損毀）。
- 沒做（後續）：V11 的 Google 對帳（帳本對 Google 表，沿用 ed-seykota「趨勢策略」分頁）；開發機演練（P3）本身；觀察區偵測副本更換單檔需另外部署到開發機。

## 教訓
「還沒產生」與「讀取失敗」要分開處理：新功能剛部署時檔案不存在是正常等待，若一律當錯誤，會在部署後幾輪內誤發通知。新增觀察檢查時，先列出每個輸入檔「尚未存在」的狀態並各寫一個測試。
