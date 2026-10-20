# 8b 停放的平倉與被拒收的更正基準留下 R1 事件日誌（v0.30.15）審閱歸檔

- PR：bcup02/trade-alerts#248
- head：99a5a34b83dd07b3811a84f7234446a0de53cc51（首審 head 9e7e696fb5bb7300284e6f6eef4a2c03621f5ce1）／ base：22949a4a0c93c3e4bea031e5d00878841c2c9319 ／ squash：26d9eac86f5f1146a43ca621bb46336dccb2f867
- 審閱：ChatGPT，2 輪（首審 BLOCK B1，複審 PASS；審閱PR#248結論：PASS）
- CI run：首審 39349543628（1144 passed）、複審 39350906388（1146 passed）
- 重點：dispatch_next_projection 新增選用參數 fleet_event_log／strategy_project；新函式 record_projection_park_event 在停放孤兒平倉或更正（ERR-056，project fleet）、趨勢更正基準被拒（ERR-068）時各記一筆 R1 事件，不通知。事件在釋放送出佇列鎖之後寫。
- BLOCK B1：事件日誌的 flock 是無逾時的阻塞鎖，事件寫入失敗有捕捉例外但等鎖不會丟例外，派送函式可能無限等待。修正：append_jsonl／append_fleet_event 新增選用 lock_timeout（預設 None＝照舊），park 事件用 2 秒、逾時放棄這一行稽核並記警告；新增兩個真實 flock 競爭測試。
- 審閱確認不阻擋：mkdir／open／fsync 等磁碟 I/O 理論上仍可能卡住，不在此 PR 範圍（策略帳本寫入同樣風險）。
- 審閱建議（非阻擋）：①requeue 後再次停放會再記一筆，目前沒有直接測試；②第一個鎖競爭測試只斷言等待上限（waited < 5），沒有下限。
- 已知限制：崩潰剛好發生在派送落盤與事件寫入之間，只會漏掉那一行稽核；只有趨勢會記 CORRECTION_BASE_MISMATCH。
- 後續：已發 tag v0.30.15；四支策略逐支改釘並傳入事件日誌路徑；登記冊等 A1 上線後再改。
- 隔離聲明：審閱者只讀 GitHub，未接觸 /opt /etc /var/lib systemd 交易所 Google 實機帳本；PASS 不等於部署授權。
