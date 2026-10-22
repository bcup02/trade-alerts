# 審閱歸檔：f-45 公開 post_receiver_json 收件端傳輸（PR #268）

- PR：bcup02/trade-alerts #268；squash `97c7a9a`（main）；tag `v0.30.17`
- head：首審 `5091ad0cdf86c0afc7248a02803dd9094229821b`（BLOCK）→ `e6aad612c4353518c3fbb9677d9a57325b3b9107`（BLOCK）→ `2e42bc725eb4e3c25239e5bc9d45970b82ea26e7`（PASS）；base `0e3070730df69f017a517f7afe2d472d89d80ba3`
- 審閱：3 輪（ChatGPT）。CI：run 39726620230（1271 passed，基線 1258）→ 39728096014（1274）→ 39729177980（1287）。

## 重點
- 新增 `google_ledger_client.post_receiver_json`：既有 `_post_json` 的公開版（只允許 https；endpoint 缺或非 https 在發請求前就拒絕）。供 ops-notify 維運健康發布單元使用，不複製轉址安全規則。
- 首審 BLOCK：`_post_json` 的 GET 沒設 `allow_redirects=False`，合法第一跳（script.googleusercontent.com）之後的第二次轉址會被 `requests` 自動跟隨，繞過主機白名單。修法：自己迴圈跟隨、每一跳過 `_permitted_redirect`、最多 3 跳、GET 帶 `allow_redirects=False`。
- 第 2 輪 BLOCK：`raise_for_status()` 對 3xx 不拋錯，307／308 或沒有 Location 的 301／302／303 若 body 是 JSON 物件會被當成成功。修法：最終回應不是 2xx 一律拋 `ValueError("receiver_unexpected_status")`。
- 兩個修正在共用的 `_post_json`，所以既有 `submit_projection_v2`、`read_projection_audit_v2`、`read_reconciliation_inventory_v2` 一併加固；合法的 Apps Script 一跳流程行為不變。

## 限制
- 沒有針對 1xx／非標準狀態碼逐一寫測試（檢查是 `200 <= status < 300`，審閱者確認範圍驗證完整）。
- 四支策略與 ops-notify 各自釘的舊版仍帶舊的 `_post_json`；加固要等各自改釘到 v0.30.17 以上才生效。

## 部署
- 不部署（新函式沒有呼叫端；對既有路徑是加固）。A1 與開發機未動。

## 隔離聲明
審閱端只讀 GitHub 程式碼、提交差異與 CI 日誌；未碰 /opt、/etc、/var/lib、systemd、交易所、Google 或 A1；未 checkout、未 push。
