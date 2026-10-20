# f-45 接收端新動作 put_health_v1 審閱歸檔

- PR：bcup02/trade-alerts#250
- head：e14db55a11911fc0bf977d4fd3ae4abd29420e9d（首審 head 3ede6124458ce411f8b399988bd3f48a948d6f64）／ base：cb6ff1814dc20540c8ca534e57f9f548099c16cb ／ squash：2bf3baa76838ce4f25f0090e3c87729ea0b24ee3
- 審閱：ChatGPT，2 輪（首審 BLOCK B1，複審 PASS；審閱PR#250結論：PASS）
- CI run：首審 39365457197、複審 39370006945（pytest 1146 passed，Apps Script node 測試 5 支全過）
- 重點：Apps Script 接收端新增 put_health_v1：A1 發布單元把壓縮後的健康表寫進分頁「維運健康」的 A1（HEALTHv1|<base64>|HEALTHEND，b64 最長 9000 字元）；來源登記新增 allowed_actions 機制，健康來源只能呼叫這個動作，沒有該欄位的既有來源永遠不能呼叫它；固定分頁名守門；分頁不存在不建立；不寫稽核分頁。
- BLOCK B1：allowed_actions 欄位存在但型別不是陣列（字串、null、物件、數字）時退回舊來源的寬鬆規則，等於權限擴張。修正：欄位存在就嚴格依陣列授權，不是陣列一律拒絕；補六個來源的路由層反例測試，並以故意弄壞版本確認測試會失敗。
- 審閱確認不阻擋、留給發布端／讀取端：①base64 只有字元檢查，不驗 gzip／JSON 結構；②5 分鐘內的舊簽章請求可能讓 A1 短暫回退為舊表（表內自帶 generated_at，頁面自己判斷過期）；③部署健康來源的 Script Properties 時要驗登記內容確實帶 allowed_actions: ["put_health_v1"]。
- 後續：未部署（正式與 DEV 試算表、Script Properties 都沒動）；A1 發布單元與登記冊頁面另案；部署需要使用者重新登入 clasp，A1 要持有獨立寫入密鑰。
- 隔離聲明：審閱者只讀 GitHub，未接觸 /opt /etc /var/lib systemd 交易所 Google 實機帳本與 Script Properties；PASS 不等於部署授權。
