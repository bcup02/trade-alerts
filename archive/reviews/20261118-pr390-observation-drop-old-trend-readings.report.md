# PR #390 審閱歸檔：觀察區穩定檢查不再要求已下線的舊趨勢策略讀數（4.1 後續）

- PR：bcup02/trade-alerts #390；squash `47dccb2`；審閱 AI：ChatGPT；結論：第 1 輪 PASS（head `a7ef85c`，base `fe7b494`，CI run 44281387566，1675 passed）。
- 範圍：`observation_watch.py` 新增 `_RETIRED_A1_STRATEGIES`／`_ACTIVE_A1_STRATEGIES`，`REQUIRED_READINGS` 21→16、`_STABLE_TARGETS` 只含現役三支與主機；`REPOS` 不動；測試改用現役三支夾具、舊趨勢範例改 momentum，新增除役測試；文件同步。
- 部署：台北 18:4x 單檔換到 A1-dev `/opt/observation-watch/`（備份 `observation_watch.py.bak-20261118-4.1`）；`phase-x8／f-63／phase-x5` 從「檢查壞了」回到「等待中」，穩定時數因中斷重算為 0。

## 為什麼會發生
4.1 把維運通知的 seykota 目標關掉前，我只查了 portfolio-query、登記冊與 e-5，沒查「觀察區偵測讀 ops-notify 狀態檔的 21 筆必要讀數」。台北 17:57 起 a1-stable 回報「檢查壞了」，約 50 分鐘後修復（只是監控誤報，不影響交易）。

## 已知缺口與後續（審閱者提出，皆非阻擋）
1. `check_sheet_tab_names`（f-26）迴圈仍含 seykota：舊策略不再有新交易，重新啟用該檢查時會一直「等待中」或讀檔錯誤；f-26 下線或驗收調整時單獨處理。
2. `_a1_event_logs` 仍讀 seykota 歷史事件日誌：若有 14 天內、符合條件的 seykota 事件且 `_export["seykota"]` 送達證據被清掉，可能判為無法證明送達（甚至逾時 FAILED）；目前沒有這種事件，下線後要另查。
3. 建議補測試：狀態檔殘留過期 `seykota:*` 時 a1-stable 不受影響。

## 教訓
1. 停某個讀數來源（維運通知目標）前，要列出「所有讀它的人」：portfolio-query、登記冊、觀察區偵測（ops-notify 讀數、事件日誌、分頁名檢查）；11/17 的前置查證漏了觀察區偵測的必要讀數集合。
