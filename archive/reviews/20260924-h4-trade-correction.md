# Perplexity 審閱歸檔 — feat: trade_correction -- append-only ledger corrections restated from exchange fills (h4)

- **Repo**：bcup02/trade-alerts
- **PR**：#58，最終 head `01222de5459b0570a279620d09113f90c702fe40`
- **base**：`main` @ `ea6a715`
- **squash 合併為**：`e97bdbd`
- **審閱者**：Perplexity — 一輪 **`PASS`**
- **CI**：pytest = success（run `35971380418`；363 passed，baseline 342，+21）；apps_script node 測試三支 passed
- **對應待辦**：機隊工程進度 `phase-h4`（後續 `phase-g1` 共用同一個更正函式）
- **部署**：本身不部署；隨下一版發佈。Apps Script 接收端需使用者另行重新部署。

## 做了什麼

新增共用的帳本更正事件 `trade_correction`（trade-correction/v1）：`build_trade_correction` 只從交易所成交重算整筆已平倉交易；
`apply_trade_corrections` 以更正後副本取代第一筆平倉，`previous` 不符即拋錯；`recorded_order_ids`／`fold_ledger_trades` 內建套用，
更正永不改變部位。Google 路徑新增 `correct_close_v2`（投影佇列強制動作↔事件類型成對），兩份 Apps Script 新增 `correctClose`，
只能取代目前生效的版本。登記冊新能力 `ledger.trade_correction`。說明見 `docs/trade-correction.md`。

## 審閱重點

審閱者以 fixture（正式機真實帳本＋交易所成交）獨立手算重現兩筆更正數字（9/21：淨損益 −13.2331294、進出 0.011；
9/18：21.44801416），確認 DIVERGED→RECONCILED、部位不變式、previous 不符必拋錯、數字只源自交易所成交、兩份 .gs 逐字一致、
既有 append_open_v2／update_close_v2 零影響、無更正事件時向後相容，九種拒絕路徑與動作成對檢查皆有測試。無阻擋、無非阻擋建議。

## 隔離聲明

開發端為取得權威數字，唯讀讀取正式機趨勢策略的帳本、交易所快照、對帳狀態與平倉投影（ssh＋cat），無任何寫入；
審閱端只用 GitHub 唯讀 API。完整差異見同名 `.patch`。
