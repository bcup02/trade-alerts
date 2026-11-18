# PR #379 審閱歸檔：拿掉觀察區 e-5 的 trend-addon 檢查（v0.30.42）

- PR：bcup02/trade-alerts #379；squash `8e8cc15`（tag `v0.30.42`）；審閱 AI：ChatGPT；結論：第 1 輪 PASS（head `d5df16b`，base `bbd3e99`，CI run 44224777931，1670 passed）。
- 範圍：`scripts/observation_watch.py` 刪除 `check_trend_addon` 與 `CHECKS` 的 `trend-addon` 註冊；2 個專屬測試刪除、覆蓋範圍斷言拿掉 e-5；版本 0.30.42。
- 原因：`trend-addon` 只看 A1 舊趨勢策略的加碼交易，舊趨勢策略已停用、封存；使用者 2026-11-18 決定移除觀察區 e-5 並一併拿掉偵測。接續 #377（f-7）。

## 審閱重點與結論
- 函式與註冊拿乾淨；`_trades_after`、`reconcile_covers`、`load_json`、`audit` 仍有其他檢查使用，沒有孤兒 helper；沒有其他檢查宣稱涵蓋 e-5。
- 舊狀態檔：完整 `run` 只保留仍在 `CHECKS` 的 id，舊紀錄會被清掉（既有測試 `test_a_check_removed_from_the_registry_leaves_no_orphan_state`）；`run --only` 會暫時保留到下一次完整 `run`，是既有語意。
- 隔離聲明：審閱者只讀 GitHub PR、repo 檔案與 Actions 日誌，未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或實機帳本。

## 部署
- 開發機單檔：台北 2026-11-18 約 10:49 換 `/opt/observation-watch/observation_watch.py`（舊檔備份 `observation_watch.py.bak-pr379`），手動跑一輪後 `observation-report` 檢查時間 10:49（台北）、報告沒有 e-5，兩台都 0 個失敗單元。正式機不涉及。

## 已知缺口與後續
1. `ALLOWED_PATHS` 的趨勢路徑白名單未縮（`sheet-tab-names` 等仍讀）。
2. 進度頁主條目 e-5 本來就是「完成」，未改。

## 教訓
無新增。
