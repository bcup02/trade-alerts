# observation-watch registry-drift（phase-sync4a） 審閱歸檔

- PR：bcup02/trade-alerts#199
- head：dca786fea711d0948da5e10bc7dc86dd19701c47（首審 9c13f82d6285c0c682f795a35b627fec9966a179）／ base：8c4c61a4bf5050b4435f6859e48eefef36d3b450 ／ squash：e1647fa06a15a1bcad38a082d58642376d23ba1e
- 審閱：ChatGPT，2 輪（第 1 輪 BLOCK，第 2 輪 PASS；審閱PR#199結論：PASS）
- CI run：38684921375（1038 passed；首審 1034）
- 重點：observation_watch 新檢查 registry-drift——登記冊引用的檔案，在 A1 部署複本上的 blob 和 sources 提交不同就點名（Remote.git_blobs，唯讀白名單；通知 key 以 project:path:A1 blob 前 7 碼去重）；收尾 SOP 補一行。
- 審閱 BLOCK：git ls-tree 輸出有認不得的行時被靜默略過，等於把「讀不到」當成「檔案不在」。修正：_parse_ls_tree 對非空且不符格式的行丟 RemoteError（A1 端與本機端共用）；A1 回答沒被問到的檔案也丟錯；引用的檔案在 sources 提交上一個都找不到（checked==0）丟錯，不回報全部一致。新增 4 個回歸測試，套回舊版全部失敗。
- 審閱接受的邊界：sources 只有部分引用找不到時仍略過那些檔案（引用合法性由 verify_registry_evidence.py 負責），WAITING 不代表所有 evidence 引用都驗過。
- 還沒做：第一則漂移通知會列 15 個檔案／33 格（sources 落後 A1 現況），由進度頁 f-47 處理。
- 隔離聲明：審閱端未接觸實機；PASS 不授權部署。
