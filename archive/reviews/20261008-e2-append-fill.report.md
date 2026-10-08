# Perplexity 審閱歸檔 — 現貨成交專用的 Google 表寫入動作 append_fill_v2（PR #145，v0.28.0，e-2）

- **Repo**：bcup02/trade-alerts
- **PR**：#145，最終 head `3ace64b017e8dddb1b553e0eba3408e69c2fef7d`（審閱的是 `0ebd6a532ef8048655cb8ae84b5f18fa00444d74`，#144 合併後 rebase，兩者樹完全相同），base `21cc805`→`2892688`（main），squash 合併為 `4a2522e`，tag `v0.28.0`
- **審閱者**：Perplexity — 兩輪：首審 head `0b017a1` **BLOCK**（B145-1）→ 複審 **PASS**
- **CI**：pytest = success（審閱 head run `37753518003`；701 passed；rebase 後 head 同樣綠燈）

## 做了什麼

接收端（兩份 .gs）新增 append_fill_v2：事件類型 spot_fill，欄位同開倉列加 source（P 欄）固定 spot_fill；共用庫的 action／事件類型／簽章與送出白名單加入 append_fill_v2／spot_fill，且 fill↔spot_fill、open↔trade_open 強制成對。起因：競賽是現貨，每筆成交被送成「只有開倉沒有平倉」的孤兒開倉列（舊待辦 E2）。

## 審閱過程

首審 BLOCK（B145-1，Medium）：新增的 receiver 錯誤碼 fill_projection_invalid 沒進 Python client 的 terminal 集合，被當可重試，永久無效的 fill 會卡在佇列最前面。修正：加入 `_TERMINAL_RECEIVER_ERRORS`；新增 client 層與 receiver 錯誤→client→outbox 流程測試（拿掉修正兩個都失敗）；補接收端「同內容換 request id」冪等測試。複審 PASS。

## 審閱者標明的界限

- duplicate_trade_id、trade_id_conflict 比照 open 路徑維持可重試，沒有單方面改成 terminal。
- #145 疊在 #144 上，PR 描述有舊計數與舊 commit；實際以最新 diff 與 CI 為準。
- 部署順序：接收端先部署；競賽改用時，佇列裡舊的 trade_open intent 會 rehydration_invalid，要挑佇列已排空時。PASS 不代表已部署接收端或競賽改用。

## 教訓

- 接收端新增的每個拒絕碼，都要走一遍「Python client 怎麼分類、佇列最前面會不會被它卡住」，不能只測接收端回了對的錯誤。

## 隔離聲明

本 PR 只動共用庫白名單、接收端原始碼（不部署）與測試；沒有下單、保護單、帳本寫入或部署變動。
