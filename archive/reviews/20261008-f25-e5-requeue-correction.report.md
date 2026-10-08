# Perplexity 審閱歸檔 — 停放的紀錄可重新排入、帳本更正不再無限重試、接收端 REJECTED 稽核列不算已處理、平倉寫回整筆進場價與數量（PR #144，v0.27.9，f-25＋e-5）

- **Repo**：bcup02/trade-alerts
- **PR**：#144，最終 head `438b8a712a4ffecf0645a941176b7854ee3f3c0b`，base `21cc805286f14534654c00b8083d8b0c5eec0251`（main），squash 合併為 `2892688`，tag `v0.27.9`
- **審閱者**：Perplexity — 兩輪：首審 head `ab96aeb` **BLOCK**（B144-1）→ 複審 **PASS**
- **CI**：pytest = success（最終 run `37753320099`；698 passed，baseline 689，+9 含 #142 的 1）

## 做了什麼

帳本更正（correct_close_v2）連續 12 次回 close_not_confirmed 記 REJECTED（correction_close_not_confirmed）停放；新增 `requeue_rejected_projection_intents`（停放的紀錄依原順序重新排入）；接收端（兩份 .gs）updateClose／appendOpen 的「已處理過」只算 CONFIRMED 稽核列；平倉寫回 G／I＝整筆進場價與數量（e-5）；ERR-056 目錄文字與行號同步。起因：f-21 開發機一筆停放的平倉，帳本更正重試 510 次擋住佇列，且重新排入會被接收端 trade_close_conflict 擋掉。

## 審閱過程

首審 BLOCK（B144-1，Medium）：requeue 用「每個 intent 最後一次 status」，CONFIRMED 後又出現矛盾的 REJECTED 時會把已送達的投影重排。修正：記每個 intent 曾出現的所有 status，曾 CONFIRMED 一律不重排；新增 3 個回歸測試（舊程式失敗已實測）。複審 PASS：審閱者用隔離重播枚舉 1,640 組歷史組合全符合。

## 審閱者標明的界限

- 部署：receiver 未更新時 requeue 仍會建新 intent，舊接收端會再回 conflict，所以要先部署並驗證接收端再重新排入（runbook 已更正）。
- 審閱者沒有跑完整 pytest／Node suite；獨立檢查是 focused 隔離重播；PR 內文的測試計數有落後的舊數字（695／696）。
- PASS 不代表已部署接收端、改釘策略、或授權實機重新排入。

## 教訓

- 新的「恢復」函式要先問「歷史裡有不可撤銷的事實（CONFIRMED）嗎」，不能只看最後狀態（比照 outstanding_projection_intents 的 terminal 模型）。
- 修一個缺口時順手查它的下游：這次平倉停放後的重新排入，被接收端的稽核列判斷擋下，是另一個缺口。

## 隔離聲明

本 PR 只動共用庫佇列、接收端原始碼（不部署）、測試與目錄文字；沒有下單、保護單、帳本寫入或部署變動。證據是開發機佇列與 A1 帳本的唯讀摘錄。
