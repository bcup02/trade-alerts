# f-43 觀察區自動偵測（f43-observation-watch）審閱歸檔

- PR：bcup02/trade-alerts#183
- head：5abb172 ／ base：b10a171 ／ squash：4b374bd171d4c892c98e18130295b1e0918b4297
- 審閱：ChatGPT，4 輪（第 1、2、3 輪 BLOCK，第 4 輪 PASS；審閱PR#183結論：PASS）
- CI run：38351708484（956 passed，baseline 890）
- 重點：`scripts/observation_watch.py`（唯讀偵測 10 項觀察區條件，結案證據分 closable／needs_human，Telegram 每次觀察只通知一次）＋開發機 systemd 計時器（每 30 分鐘）＋文件。各輪 BLOCK：①對帳要晚於交易加 61 分鐘寬限、送達證據分層、唯讀白名單改確切路徑、加檔案鎖；②ops-notify 首次建立基準時 `delivered` 是略過標記不是送出；③狀態檔要在取得鎖之後才讀（`run`、`ack` 都是）。
- 已知限制：對帳 RECONCILED 是時間水位推論，不是逐筆寫入回執；第二則訊息的送出只有失敗紀錄，沒有成功證據；狀態檔存不進去時已發的通知可能重複；`ack` 等鎖沒有獨立逾時。
- 隔離聲明：新增檔案，不改函式庫與策略；PASS 不等於部署授權（開發機已安裝，A1 沒動）。
