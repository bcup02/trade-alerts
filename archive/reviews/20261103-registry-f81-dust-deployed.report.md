# 審閱歸檔：PR #335 登記冊跟上 f-81 粉塵轉換擴充已部署 A1

- PR：bcup02/trade-alerts #335，squash b821296（最終 head 0d9737fca4e53c3179c183b8ec5319e3f05579a0，base 2e69c6ce）
- 審閱者：ChatGPT。兩輪：首審 BLOCK-335-01，複審 PASS（0 個阻擋項）。
- 內容：競賽 `sources` 換成 cba8efb；`ledger.dust_convert` 7 個引用搬移＋3 個新引用、`ledger.capital_flow` 2 個行號、`bear.paxg_asset` 限制句；`docs/registry-a1-checks.json` 新增 A1 查證；`recent_changes` 兩筆；頁面重產。
- BLOCK-335-01：我把 A1 日誌的 JST 當台北時間寫（「台北 18:09」，實際台北 17:09；每日 10:00 JST＝台北 09:00），審閱時台北才 17:31，時序矛盾。已全部更正並把「從未在任何環境轉換」收斂成「目前可查紀錄沒有」。教訓：A1／A1-dev 時間寫進文件前先換算並註明 JST 原值（第四次）。
- sources 換版比對：舊提交那行文字＝新提交新行號那行文字，7 筆全同（ChatGPT 獨立重算一致）；`runner.py:695` 被腳本標 changed 為多行 lambda 誤報，runner.py 與 trade_ledger.py 兩提交 blob 相同。
- CI：run 41612452516，1580 passed；`render_guides.py --check`、`verify_registry_evidence.py` 非 CI 步驟，本機 0 problem。
- 非阻擋建議（採納）：留存 A1 原始唯讀輸出，如下（2026-11-03 台北 17:51 擷取）：
  - `btc-competition-daily.timer` `ActiveEnterTimestamp=Tue 2026-11-03 18:09:30 JST`（台北 17:09:30）。
  - `btc-competition-dust-convert.service` 日誌：11/01、11/02、11/03 10:00 JST 各一行 `dust_convert skipped: no leftover coins`；11/03 18:09:45 JST 手動跑同樣略過。
  - 部署後手動跑 `btc-competition-reconcile-fetch.service`：`value=RECONCILED`；`systemctl --failed` A1、A1-dev 皆 0 個。
  - A1 `symbols.NON_USDT_ASSETS` 實測 `['BNB','BTC','ETH','PAXG','SOL']`。
- 限制：審閱者沒有連 A1、沒有本機 checkout，以 GitHub 資料與 CI 日誌為準。
- 部署：不用；合併後重發兩張登記冊。
