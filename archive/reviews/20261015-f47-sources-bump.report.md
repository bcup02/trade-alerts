# 登記冊 sources 換到 A1 現行版（f-47） 審閱歸檔

- PR：bcup02/trade-alerts#204
- head：30e553c494e9da0053ef0b842f94cd6e07378748（首審 8f6fb824add900e4fbd9bfb9ebc50b85141dee7c）／ base：420e94c81710fe8becc78446a461c30f79833f70 ／ squash：b14087a10520cc646a222a5b3168aa2c630b9428
- 審閱：ChatGPT，2 輪（第 1 輪 BLOCK，第 2 輪 PASS；審閱PR#204結論：PASS）
- CI run：38696347674（1046 passed）
- 重點：動能 53e04ce→71e6047、趨勢 489bbcd→9e487c0、競賽 7d499bb→a8a1ba1（加密不動）；28 格、37 處引用行號隨之搬動；舊提交行文字＝新提交新行號文字逐筆比對；A1 /opt 99 檔唯讀 hash 比對（98 一致，加密 tests 檔在 /opt 沒部署、複本內相同）；observation_watch 的 registry-drift 換版後回到「全部一致」（94 個引用檔）。
- 審閱 BLOCK（證據門檻）：①動能 reconcile_apply.py 新增 f-32 快照新鮮度檢查，pending_age_cap 格沒寫前提→補進 evidence（新增引用 :113，unpaired 人工比對後放行）；②沒搬動的引用缺全量比對→貼 198 組唯一組合／330 次引用全量表（0 失配）＋7 處只寫行號的引用；③A1 99 檔雜湊缺原始輸出→貼 A1 唯讀原始輸出與逐檔表。教訓：審閱端連不到 A1，換版 PR 一開始就要貼全量比對表與 A1 原始輸出，不等 BLOCK。
- 審閱接受的邊界：A1 證據是開發端提供不是審閱端親驗；只涵蓋登記冊引用的檔案，不代表 /opt 全部檔案一致。
- 還沒做：ERR-060 處理步驟沒提「快照過舊要先重跑抓取」（A1 每 15 分鐘自動刷新，影響小；待與 f-46 一起改）。
- 隔離聲明：審閱端未接觸實機；PASS 不授權部署。
