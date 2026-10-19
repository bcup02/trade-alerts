# f-55 觀察區 a1-crypto-equity（A1 加密權益低於 90 USDT 提醒）審閱歸檔

- PR：bcup02/trade-alerts#246
- 第 1 輪 head：e24dc3d400b2a14e4b3dabeddc84b477edf8287a ／ 第 2 輪 head：120958681467f9107d8ab626fede3634242b5898 ／ base：0cbbe026040b6a010f735a9cf47ff62c9e43a89e ／ squash：abed16f0a5d9e49b86779798a527feca1c0c4a6a（沒有版本號變動，不打 tag）
- 審閱：ChatGPT，2 輪（第 1 輪 BLOCK B1／B2，第 2 輪 PASS：審閱PR#246結論：PASS）
- CI run：39282937637（第 1 輪，1127 passed）、39288141609（第 2 輪，1139 passed）；四支 apps_script node 測試皆通過
- 重點：新增 scripts/observation_watch.py 的 check_crypto_equity（Check id a1-crypto-equity，涵蓋 f-55）：權益 ＝ exchange_state.json 的 balance.wallet_balance ＋ 所有 positions[].unrealized_pnl；< 90 USDT 發一則 Telegram，每 10 USDT 區間一次、回升後再跌破再通知；讀不準一律 error。
- B1（BLOCK）：第 1 版用 balance.unrealized_pnl，producer（binance_reconcile_fetch._balance_block）把它填成 Binance crossUnPnl，只含全倉持倉；A1 加密是逐倉，會漏掉持倉虧損（錢包 95、逐倉虧 20 → 誤報 95）。這在 A1 真讀數上也看得到：餘額欄位 0.0、持倉未實現 −0.53。修正：改用持倉 unrealized_pnl（unRealizedProfit）加總，並要求 fetch_status.complete、positions 為清單、每筆有限；文件寫明限制「只查策略自己的交易對」。
- B2（BLOCK）：兩個有限數相加可能溢位成 inf 而落入 WAITING。修正：相加後再檢查有限，否則 error；新增正負溢位測試。
- 非阻擋：①通知 key 命名（below-80 容易誤讀成低於 80）→ 已改 band-80-90。②fetch_status 若不是物件會在 .get() 丟例外，但由 run_checks 轉成 ERROR，不會誤報正常。③多持倉累加的中間值溢位，最終 _finite() 仍會拒絕。④舊 key 相容：檢查是新的、尚未部署，沒有舊 key。
- 後續：合併後在開發機跑 deploy/observation-watch/install.sh（2026-10-19 台北 00:57 部署，安裝檔與 repo 檔 cmp 相同，手動跑一輪報告出現 f-55「A1 加密權益 119.65 USDT，高於 90 USDT 提醒線」，0 失敗單元）。
- 隔離聲明：只改觀察區偵測工具、測試與文件；沒有碰任何策略程式與設定，沒有新增可讀路徑；PASS 不等於 A1 部署授權（本 PR 與 A1 無部署關係，A1 只讀）。
