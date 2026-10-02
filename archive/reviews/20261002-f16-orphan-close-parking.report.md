# Perplexity 審閱歸檔 — f-16 共用庫：停放找不到開倉列的關單（PR #105）

- **Repo**：bcup02/trade-alerts
- **PR**：#105，head `4caf434c6f6cf76c855bf44441c2f7053545b477`，base `0838a71a304acd05d57356f3f2d9fe6ac27ddc98`（main），squash 合併為 `c972e9e93a230d6455f72c06fd8b55229c08111c`
- **審閱者**：Perplexity — 一輪，**`PASS`**
- **CI**：pytest = success（run `36977791765`；447 passed，baseline 444）

## 做了什麼

`dispatch_next_projection`：`update_close_v2`／`correct_close_v2` 連續 12 次回 `trade_id_not_found` 後改記 REJECTED（`orphan_close_no_open_row`），佇列往下走。開倉不會被停放，其他失敗碼讓連續計數歸零。+3 個測試（含拿掉 action 條件的變異測試確認會失敗）。

## 背景

開發機動能自 2026-09-24 16:01 起被一筆關單卡住：該部位是重啟後接管來的、帳本沒有 trade_open、表上沒有對應列，重試 1419 次，後面 16 筆一次都沒送。

## 審閱結論與重點

全項 PASS：停放須同時符合「TRANSPORT_FAILED、trade_id_not_found、關單類 action」；連續計數只看同一 intent、被其他結果打斷即歸零；第 12 次才停放、前 11 次佇列頭不變；開倉不被停放；缺口不被隱藏（仍報 DIVERGED，drain 回非 0）；暫停語意（LedgerUnreadableError）不受影響。審閱者註明本輪未建立完整 exact-head checkout、未本機重跑 pytest。

## 隔離聲明

審閱者唯讀；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或正式機帳本。
