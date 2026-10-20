# 觀察區通知改送 LINE（失敗補送 Telegram）審閱歸檔

- PR：bcup02/trade-alerts#254
- head：91e6b1ab33d6ad5f70126586910848d62e4117df（首審 head 96c1f12176afda4498e1b236c2f8254b7ea3dc39）／ base：1792b82cdb80280401a3de363f91ea007fbc966f ／ squash：10a1d7e7f9463f43a7382a20ce637d8c380d3000
- 審閱：ChatGPT，2 輪（首審 BLOCK B1、B2，複審 PASS；審閱PR#254結論：PASS）
- CI run：首審 39400456081（1177 passed）、複審 39401300526（1196 passed）
- 重點：觀察區偵測腳本的所有訊息改先送 LINE（send_line，標準函式庫），同一則 LINE 連續失敗 2 輪（約 1 小時）才補送一次 Telegram 並註明；失敗計數存在檢查狀態的 send_failures；兩個通道都失敗不標記已送。安裝腳本把 LINE 與 Telegram 設定從 ops-notify.env 補進 watch.env（值不顯示）。
- BLOCK B1：安裝腳本對選用的 Telegram 備援也強制要求來源檔，LINE 完整但沒有 Telegram 時安裝失敗 → env 補齊抽成 watch_env.sh 的 ensure_watch_env，LINE 必要、Telegram 只警告，五個情境用暫存檔測試。B2：損壞的 send_failures.n（字串、負數、None…）會讓 int() 拋例外中斷整輪通知 → _failed_runs 嚴格驗證、_delivered 吞掉送出函式例外（不記錄內容，避免金鑰）。
- 審閱已知限制：LINE 推播已成功但回應逾時時可能重複通知（無跨通道 exactly-once）；整個 entry 結構被外部破壞仍可能拋例外（另案）。
- 後續：合併後在開發機用 install.sh 部署並送真的 LINE 測試訊息。開發機 11/3 前除役（f-9），腳本與 watch.env 要跟著搬家。
- 隔離聲明：審閱者只讀 GitHub，未呼叫真實 LINE／Telegram、未接觸 /opt /etc /var/lib systemd；PASS 不等於部署授權。
