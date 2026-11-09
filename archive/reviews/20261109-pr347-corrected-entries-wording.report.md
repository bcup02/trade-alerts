# PR #347 審閱歸檔：四支舊策略「已照交易所自動更正」條目不再宣稱 Google 表與 LINE 查詢已一致（v0.30.28，進度頁 f-88）

- PR：bcup02/trade-alerts #347；squash `41dd39b`；tag `v0.30.28`；審閱 AI：ChatGPT；結論：首審 PASS（head `0cdf4ed0`，CI run 42556150567，1597 passed）
- 範圍：目錄 ERR-036 趨勢、ERR-038 動能、ERR-040 競賽、ERR-067 加密的 `auto_action`、`what`、`direction`、`steps`；新增一個文字契約測試；`docs/fleet-error-catalog.md` 說明；風險登記冊頁面重新產生；pyproject 0.30.28。程式行為沒改。
- 查證結果（讀各策略 origin/operations）：四支的 `after_trade_correction`（競賽 `append_spot_fills`）只把 Google 更正入隊，派送另外做、入隊也可能失敗；LINE 查詢只有趨勢另發公開事件（盡力而為），動能與加密沒有推送、持倉快照由帳本重算才套用更正，競賽沒查到對應推送所以條目不提。結果欄位：趨勢／動能／加密在 `details.post`，競賽在 `details.written`。
- 審閱非阻斷建議：①PR 內文舊測試數字（已更正）；②日後補強 `details.post`／`details.written` 位置的測試斷言（目前是文字片段斷言）。
- 沒做（後續）：共用處理器通知本文 `notice_text` 沒帶入 `post`／`written` 的入隊結果，入隊失敗時通知仍不提；四支策略改釘 v0.30.28；競賽策略 LINE 查詢是否讀帳本沒逐項驗證。

## 教訓
V11 的 ERR-076 審閱抓到的措辭問題，其他四支同一組條目照樣存在：同類措辭有一條被糾正，就要立刻把同批條目逐支對照程式重掃，不等下一輪審閱。這次先逐支讀 `after_trade_correction` 與投影佇列程式再改文字，一輪審閱 PASS。
