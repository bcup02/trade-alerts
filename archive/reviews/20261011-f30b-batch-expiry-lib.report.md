# 審閱歸檔：競賽調倉批次逾時通知一次（PR #164，f-30，v0.30.1）

- PR：bcup02/trade-alerts #164；squash `dab85280224db9f88fe72bd2330f66e5318ff435`；tag `v0.30.1`（指向該 squash）
- 最終 head `1afab1405e1f0d8e254e264b7d970a00b8e9e2db`；base `83fbb864518b16d00befc31f4aca0ac5387dab08`
- 審閱：2 輪。首審 BLOCK（head 3e5b83c）、複審 PASS（head 1afab14）。CI：run 38061596895（840 passed）→ run 38062767147（849 passed）。

## 重點
- `announce_batch_expired`：競賽對帳超過 24 小時不再等未結算批次、且餘額一致時，每段卡住的期間通知一次（ERR-061，R3）；讀已通知與追加同一把鎖，失敗拋出由呼叫端隔離。

## 首審 BLOCK 與修正
1. 時間讀不出來時不同期間共用同一身分、永久漏通知 → 期間身分改為 since → episode_ids（等待中帳本事件編號）→ 否則同一 UTC 日最多一筆。
2. 空字典證據也發 R3 → 要求已知 reason 與有限正數 max_hours。

## 審閱列出的後續驗收（競賽整合 PR）
episode_ids 要來自穩定、可追溯的帳本事件編號；超過 50 個時改用完整集合的穩定雜湊（或確認實際數量）；bool 型別排除；f-28 同一期間的 since 要穩定；呼叫端要隔離例外。

## 隔離聲明
審閱只透過 GitHub 唯讀；開發端未接觸正式機、交易所、Google 或實機帳本；函式庫，無部署。
