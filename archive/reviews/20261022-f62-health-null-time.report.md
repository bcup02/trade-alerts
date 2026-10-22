# PR #273 審閱歸檔：維運讀數表允許單筆讀數時間為 null（f-62，v0.30.18）

- PR：bcup02/trade-alerts #273
- base：3f88319735db043a139d30b2600c3a47c3b1a0e8；最終 head：425af8e8dec18d2016712ad85a368db01fb33fa0
- squash：4fbc069dbaa00e79c394ca0cfe7562081250f62b；tag：v0.30.18（打在 squash commit）
- 審閱：ChatGPT 共 3 輪；第 1、2 輪 BLOCK，第 3 輪 PASS
- CI：run 39792674855，pytest 1470 passed，`*_node_test.js` 全過

## 重點
- `validate_health_table` 允許單筆讀數 `checked_at` 為 `null`（鍵仍必填，其他壞值照拒）。
- 第 1 輪 BLOCK：Python 與頁面端文字長度（200 UTF-16 單位）、控制字元、讀數筆數（100）的限制不一致 → 補齊，並新增兩端共用的測試向量檔。
- 第 2 輪 BLOCK：非 Z 偏移的非法日曆日期頁面接受而 Python 拒絕 → 兩端改用同一條寫死的 ISO 規則（另發現並修正 Python 接受 `+08:60` 而頁面拒絕的反向差異），向量擴充至 54 個時間字串與 54 個表格案例；開發端以約 16000 組隨機輸入比對，修後 0 差異（審閱者未獨立重跑）。
- 已發布的一致性登記冊因內嵌頁面程式變動而成為過期，之後填 file_id 重發時處理；本 PR 不發布、不部署。
- 審閱者提醒：跨語言共用向量要留在 CI；消費專案（ops-notify 等）仍須釘選已驗證版本。

## 隔離聲明
審閱者唯讀 GitHub 來源，未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或實機 state／ledger。
