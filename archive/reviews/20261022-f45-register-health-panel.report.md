# 審閱歸檔：f-45 一致性登記冊「維運讀數」面板（PR #270）

- PR：bcup02/trade-alerts #270；squash `50af7b0`（main）；無版本變更、無 tag
- head：`f1698923673e5b7d222d8856f747a7e67ab3cfca`（BLOCK）→ `26cd9278dcd6087dd856ec1732200803c6ef0b3c`（PASS）；base `78046d35c0225cafec367b47359230fa58233725`
- 審閱：2 輪（ChatGPT）。CI：run 39757208230（1309 passed，基線 1287）→ 39761692470（1309，本輪新增的是 Node 測試）。

## 重點
- 一致性登記冊最上方新增「維運讀數」面板：用檢視者自己的 Google Drive 連接器（`read_file_content`）讀獨立試算表「維運健康」A1 的讀數表，顯示對象×軸矩陣。解析與判斷在 `scripts/health_panel_core.js`（純函式），頁面與 Node 測試載入同一個檔案；頁面測試用假 DOM＋假連接器跑整個頁面指令碼。
- 過期規則：`generated_at` 超過 25 分鐘＝發布停；`checked_at` 超過 45 分鐘＝輪詢停；單格超過 45 分鐘＝該格過期；任何時間比瀏覽器現在晚超過 5 分鐘＝時鐘不一致；過期與時鐘不一致都灰掉、不顯示成正常；讀數時間為 null（f-62）標「無讀取時間」。
- 不可信資料：結構逐項驗證、長度與筆數上限、gzip 解壓上限 200 KB、一律 textContent。
- 首審 BLOCK：只檢查整張表的時間是否超前，單格 checked_at 超前時年齡為負數，過得了所有過期判斷，severity 為 ok 就顯示正常。修法：任何非 null 的單格時間超前超過 5 分鐘都讓整張表標時鐘不一致。

## 限制
- sources 檔的 file_id 目前是 null：面板只寫「還沒設定」、不呼叫連接器；獨立試算表與 Apps Script 專案要使用者建，之後填 file_id、重新產生頁面並重發（重發要帶 HEALTH_CAPABILITIES，用到連接器的頁面不能公開分享）。
- 沒有在真實瀏覽器或真實連接器上驗證（外觀、Drive 回傳格式、DecompressionStream 可用性）。
- 共用庫表格 schema 尚不允許讀數時間為 null（f-62），面板已能顯示。
- 其他過期判斷邊角（瀏覽器時鐘本身飄移、帶偏移量的時間字串）沒有窮舉。
- 沒有新增一致性登記冊的「維運讀數表」列（A1 部署並驗證後才登記為已做）。

## 部署
- 不部署。登記冊頁面尚未重發。

## 隔離聲明
審閱端只讀 GitHub 程式碼、提交差異與 CI 日誌；未碰 /opt、/etc、/var/lib、systemd、交易所、Google 或 A1；未 checkout、未 push。
