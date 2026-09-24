# Perplexity 審閱歸檔 — feat: unrecorded exchange fills -- correct only a certain duplicate send (g1-1)

- **Repo**：bcup02/trade-alerts
- **PR**：#67，首審 head `c4beeaf9109664e530fbe4f4f00ae3002c5041c9`（BLOCK）→ 複審 head `a369e53e6e55610992e17e2ae5204b2044102fc2`（PASS），base `main` @ `7ba0ffb`，squash 合併為 `58132ef`
- **審閱者**：Perplexity — **`BLOCK` → `PASS`**
- **CI**：pytest = success（run `36021672528`；380 passed，baseline 363：+17）
- **對應待辦**：機隊工程進度 `phase-g1`（g1-1）；不發版（v0.23.0 另開）

## 做了什麼

新增共用處理程式 `trade_alerts.unrecorded_fill`：接手對帳列出的帳本未記成交（`unmatched_exchange_fills`）。使用者 2026-09-25 定案：只有確定是策略自己重複送單
（交易所 clientOrderId 與帳本已記某張單相同）、交易已平倉、交易所成交能完整重述，且一併納入的其他未記單也逐張證明是策略下的，才自動追加更正（期貨 trade_correction／現貨補記 spot_fill），
並一律 R3 立刻通知；其他一律不寫帳本，開請求＋R3（ORIGIN_UNKNOWN／POSITION_OPEN／UNATTRIBUTED_ORDERS／NOT_RESTATABLE／LOOKUP_FAILED／WRITE_FAILED／NO_CLIENT_IDS）。
目錄新增 7 條 R3、登記冊 pending。以 9/21 真實 fixture 得出與 h4 人工更正相同的結果（0.008→0.011 BTC、淨損益 −10.387→−13.233）。

## 審閱經過

- **首審 BLOCK**：`_correct_trade` 把同交易時段 ±10 分鐘內的所有未記訂單併入重述，只有最初那張做過 clientOrderId 驗證；App 手動單剛好落在同時段且數量能平衡時，會被一起寫進 trade_correction，違反「只有確定重送才寫」。
  其餘（寫前重讀、寫後驗證、每輪一次、WRITE_FAILED 不重試、請求／撤回、spot 路徑、R3 目錄）方向正確。
- **修正**：轉接器新增 `owns_client_order_id` 謂詞；額外納入的每張單須 clientOrderId 等於這次重送的編號或屬策略自有編號體系，否則整組 UNATTRIBUTED_ORDERS、零寫入；查單例外 fail closed。補兩條回歸測試（在前次 head 上皆失敗）。
- **複審 PASS**：確認漏洞封住（未歸因訂單在 fetch_fills／build／寫入前就終止）、測試非假陽性、9/21 主案例改由 `sk-` 編號規則顯式歸因而非放寬。

## 後續

g1-3 接趨勢策略前，先唯讀查正式機 9/21 停損出場單的 clientOrderId 形式，再定趨勢策略的 owns 謂詞。

## 隔離聲明

只動 trade-alerts 的共用模組、測試、目錄／登記冊 JSON、文件與產生的頁面；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或正式機帳本；未接任何策略、未部署。完整差異見同名 `.patch`（src、tests、docs/fleet-error-catalog.md）。
