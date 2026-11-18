# PR #377 審閱歸檔：拿掉觀察區 f-7 的兩個檢查（v0.30.41）

- PR：bcup02/trade-alerts #377；squash `678a742`（tag `v0.30.41`）；審閱 AI：ChatGPT；結論：第 1 輪 PASS（head `7408219`，base `168738b`，CI run 44222535718，1672 passed）。
- 範圍：`scripts/observation_watch.py` 刪除 `check_dev_trend_entry`、`check_dev_trend_reconcile` 與兩筆 `CHECKS` 註冊；對應 3 個專屬測試刪除、3 處斷言／混合測試改成不含這兩項；`docs/observation-watch.md` 標註已拿掉；版本 0.30.41。
- 原因：開發機舊趨勢策略已停用，對帳狀態停在 11/11，這兩個檢查每輪報「檢查壞了」（連續 355 次）；使用者 2026-11-18 決定移除進度頁觀察區 f-7。

## 審閱重點與結論
- 兩個檢查與註冊拿乾淨、沒有孤兒 import；其餘 CHECKS 與共用 helper（`audit`、`load_json`、`_fresh`、`reconcile_covers`）與 base 相同。
- 舊狀態檔相容：完整 `run` 只保留仍在 `CHECKS` 的 id，退休檢查的舊紀錄會被清掉（既有測試 `retired` 覆蓋）；`run --only` 會暫時保留舊紀錄到下一次完整 `run`，是既有語意。
- 隔離聲明：審閱者只讀 GitHub PR、repo 檔案與 Actions 日誌，未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或實機帳本。

## 部署
- 開發機單檔：台北 2026-11-18 10:25 換 `/opt/observation-watch/observation_watch.py`（舊檔備份 `observation_watch.py.bak-pr377`），手動跑一輪後 `observation-report` 檢查時間 10:25（台北）、報告不再有 f-7、兩台都 0 個失敗單元。正式機不涉及。

## 已知缺口與後續
1. `ALLOWED_PATHS` 的 seykota 讀取白名單未縮（`trend-addon` 仍讀 A1 路徑；開發機那兩個路徑只是不再被讀）。
2. 進度頁主條目 f-7 的狀態未改（等使用者決定結案或標成不做）。

## 教訓
無新增。
