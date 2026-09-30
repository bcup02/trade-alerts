# 維運通知告警補進錯誤清單 ERR-043～049（e2）

- PR：[bcup02/trade-alerts#89](https://github.com/bcup02/trade-alerts/pull/89)，head `cb0433d`，squash 合併 `e360af7`（base `0507b90`）
- Perplexity：一輪 **PASS**
- CI：pytest 385 passed（run 36661881802）

## 內容

維運通知依狀態軸自己組的 LINE 告警補成 7 條 `FLEET.OPS_*`（等級使用者 9/30 同意）：R3 帳本↔交易所對不上、策略出錯或安全暫停、主機時鐘同步被關；
R2 帳本↔Google 表對不上、背景服務掛掉、匯出檔讀不到、策略停止回報。「背景服務掛掉」同時登錄 9/29 新主機快照資料夾漏建事件。
一致性登記冊 7 列：正式機有盯的軸標已做、加密策略服務單元／匯出檔軸未做（第 8 關）、時鐘主機層級不適用、寫進事件日誌一律不適用。
另補退役條目保留 error_id 的正向測試。通知文字不變（帶編號是 e3）。不用部署。

## 審閱重點

審閱者確認 7 條等級與處理語意、登記冊 done/pending/n-a 語意、ERR-001..049 不變式、新測試非假陽性。限制：審閱工具讀不到
ops-notify 私有 repo 的原始行，行號由開發端逐行核對（見 PR 描述），審閱者判定非阻擋。

## 隔離聲明

只動 catalog／registry JSON、兩張產生頁與一個測試；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google、實機帳本或 ops-notify 程式。
完整差異見同名 `.patch`。
