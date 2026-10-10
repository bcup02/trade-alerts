# 審閱歸檔：位置對帳標記最多等 24 小時，逾時通知一次（PR #162，f-30，v0.30.0）

- PR：bcup02/trade-alerts #162；squash `df2c2f5bd0d736e70b91fbf88785d5cfb423ea37`；tag `v0.30.0`（指向該 squash）
- 最終 head `bdd186fe433fd1ac6b6a82f3f9c474640711dc5f`；base `cae0beee0e4fba314a34a9f19fdab4d4545e3b36`
- 審閱：2 輪。首審 BLOCK（head 9df7811）、複審 PASS（head bdd186f）。CI：run 38057305503（816 passed）→ run 38057976308（826 passed）。

## 重點
- `exchange_ledger_compare` 新增 `pending_max_seconds`（預設 24 小時）；標記逾時或時間不可信即不再等，部位與成交先比對，所以不隱藏真正不一致。
- 新增 `pending_expired_notice`，`repair_runner` 每輪對「一致」狀態下的逾時標記各通知一次（ERR-060，R3）。

## 首審 BLOCK 與修正
1. 通知步驟失敗會中斷修復輪、並行輪可能重複通知 → 讀已通知清單與追加放進 `exclusive_log_lock`，整段包 try/except，失敗下輪重試；測試 8 輪並行只發一次。（事件日誌損毀時整輪本來就大聲失敗是既有契約，未改。）
2. DIVERGED 仍可能發「已對上」通知 → 只在 `value == "RECONCILED"` 通知。
3. 同批重複交易編號 → 去重。

## 後續（另案）
動能改釘 v0.30.0 必須與 `reconcile_apply.py` 認「一致但有逾時標記」同批；競賽的逾時通知；f-31。

## 隔離聲明
審閱只透過 GitHub 唯讀；開發端未接觸正式機、交易所、Google 或實機帳本；函式庫，無部署。
