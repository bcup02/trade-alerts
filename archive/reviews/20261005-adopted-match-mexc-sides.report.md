# Perplexity 審閱歸檔 — 接手成交配對也認 MEXC 成交方向代碼（PR #121，v0.27.2）

- **Repo**：bcup02/trade-alerts
- **PR**：#121，head `3e3a87efdfbbe349040edc50767535fb51ec80cf`，base `9db15dbfeef2e8265ef34f9ef71a8fdabe2b967f`（main），squash 合併為 `957e0b3`
- **審閱者**：Perplexity — 一輪：首審 **PASS**
- **CI**：pytest = success（run `37285557436`；639 passed，起始 632）

## 做了什麼

動能（MEXC 期貨）的成交方向是 open_long／close_long／open_short／close_short，v0.27.0 的配對函式只認 buy／sell。作者用動能的 reconcile_compare.compare 實測：同一筆接手倉位，open_long 得 DIVERGED、buy 得 RECONCILED。新增 `_ADOPTED_FILL_SIDES`：多單進場＝buy／open_long、多單平倉＝sell／close_long、空單進場＝sell／open_short、空單平倉＝buy／close_short；其餘條件不變。新增 7 個測試。版本 0.27.2。

## 審閱重點

- 四種候選 × 四個 MEXC 標籤 16 格，每種候選只接受自己的標籤；buy／sell 行為與 v0.27.1 等價（16 組比對相同）；一筆 buy 同時有多單進場與空單平倉候選時只配一次。
- 大小寫不敏感；空值、None、bool、數字、NaN、空容器、帶空白字串、未知字串都不配對。

## 審閱者標明的界限

- side 以 `str(value or "").lower()` 轉字串（既有設計），自訂物件若 `__str__` 回傳合法標籤仍會被接受；一般 JSON 值沒有誤配，不列阻擋。
- buy／sell 本來就可同時符合多單進場與空單平倉，是保留的 Binance 風格契約；一筆成交不會被兩列同時採用。
- 全量回歸以 CI 為準；趨勢結論只限函式契約，沒跑趨勢 repo 測試。PASS 不代表可部署、發 tag 或改釘版；動能消費端仍需驗證實際資料與紙上分類。

## 隔離聲明

審閱者唯讀；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或實機帳本。合併不代表任何主機部署。
