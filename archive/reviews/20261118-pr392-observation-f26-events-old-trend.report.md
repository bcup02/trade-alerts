# PR #392 審閱歸檔：觀察區分頁名檢查與事件日誌檢查不再看舊趨勢策略（f-96／f-97／f-98）

- PR：bcup02/trade-alerts #392；squash `e7baf1a`；審閱 AI：ChatGPT；結論：第 1 輪 PASS（head `8a7c4fc`，base `3a912b4`，CI run 44290238492，1678 passed）。
- 範圍：`check_sheet_tab_names` 迴圈改 `_ACTIVE_A1_STRATEGIES`（三支）；`_a1_event_logs` 拿掉 seykota（歷史事件檔不刪、`ALLOWED_PATHS` 不縮）；新增三個回歸測試；文件字樣同步。這三項是 PR #390 審閱提出的尾巴。
- 部署：台北 19:03 前後單檔換到 A1-dev（備份 `observation_watch.py.bak-20261118-f96`），兩台 0 個失敗單元。

## 已知缺口與後續（審閱者建議，非阻擋）
1. f-96 測試名稱寫「missing file」但 fixture 仍有 seykota 檔案，沒有直接模擬檔案不存在；source 已確認迴圈不再訪問 seykota。
2. f-97 測試選的 `check_momentum_halt_notice` 本來就只篩 momentum，更直接的負面測試應用 `check_safe_halt_notice` 或直接驗 `_real_events` 不回傳 seykota 事件。
3. `REPOS`／`SHEET_NAMES`／`LABELS` 仍含 seykota（登記冊 sources 與部署複本比對用），封存舊趨勢時再處理。

## 教訓
1. 同 PR #390：停掉讀數來源前，列出所有讀者。迴圈寫 `for key in REPOS` 的檢查，在策略下線時都要重新判斷。
