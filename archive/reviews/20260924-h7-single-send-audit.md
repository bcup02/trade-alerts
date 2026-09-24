# Perplexity 審閱歸檔 — docs: h7 single-send audit -- momentum/mycrypto done, btc gap + BTC.ORDER_STATUS_UNKNOWN

- **Repo**：bcup02/trade-alerts
- **PR**：#56，最終 head `da738b61c3fa0b1c81bf82161662db7ea029b8fc`
- **base**：`main` @ `653d106`
- **squash 合併為**：`7a7a5e6`
- **審閱者**：Perplexity — 首審 **`PASS`**（head `e167734`）→ 複審 **`PASS`**
- **CI**：pytest = success（首審 run `35955757972`、複審 run `35957588743`；342 passed，純資料變更 +0）
- **對應待辦**：機隊工程進度 `phase-h7`、`phase-h9`
- **部署／發版**：不發版；錯誤清單新代碼隨下一版共用程式庫發布（與 h6 同批）。合併後重新發布兩張登記冊頁面。

## 做了什麼

#50 審閱 BLOCK 的 `orders.single_send` 三格查核結果（對 sources 記錄的 operations commit 逐路徑讀程式＋模擬「送單逾時但其實已成交」重跑）：
- momentum → done（回歸測試＋自我檢查行為檢查 mexc-4h-momentum-trailing-stop #100）。
- mycrypto → done（回歸測試 my-crypto-bot #49）。
- btc-competition → 仍 pending，phase `hotfix-btc-order-resend`：收斂迴圈對任何單腿例外都用新 client id 重規劃再送，已重現；修正 btc-bull-market-competition #35。
- 錯誤清單新增 `BTC.ORDER_STATUS_UNKNOWN`（JUDGEMENT／R3／latch）＋登記冊列（pending）；移除已無人使用的 `single-send-audit` phase；
  錯誤清單說明文件計數改回與 JSON 一致（37 條——v0.21.1 退役兩條 `*_PROPOSED` 時沒跟著改）。

## 審閱

- 首審 PASS。審閱者揭露的信任邊界：私有 repo 原始碼讀不到，evidence 行號與 `verify_registry_evidence.py` exit 0 未獨立覆核，改以 #100／#49 的測試斷言交叉驗證行為、以算術重建文件計數與 HTML totals。
- btc #35 審閱修正使 `raise OrderOutcomeUnknown(` 下移 5 行，以 commit `da738b6` 把 sources `executor.py:302` 改為 `:307`；複審以行號位移推算確認，PASS。

## 隔離聲明

只動錯誤清單／登記冊 JSON、錯誤清單說明文件與兩個 `scripts/render_guides.py` 產生的 HTML；無程式碼、部署或秘密變更。完整差異見同名 `.patch`。
