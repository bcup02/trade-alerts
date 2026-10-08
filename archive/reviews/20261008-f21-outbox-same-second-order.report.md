# Perplexity 審閱歸檔 — Google 表同步佇列：同一秒排進去的紀錄照排入順序送（PR #142，v0.27.8，f-21）

- **Repo**：bcup02/trade-alerts
- **PR**：#142，head `52c33cc28bfdc5d61a9254e66c9443fd87f6fe83`，base `8c273d5c219c115a7dbbf007abc59cd88221e962`（main），squash 合併為 `14cc4a5`，tag `v0.27.8`
- **審閱者**：Perplexity — 一輪首審 **PASS**
- **CI**：pytest = success（run `37727122419`；690 passed，baseline 689，+1）

## 做了什麼

`outstanding_projection_intents` 不再以 `(created_at, intent_id)` 排序，改照檔案寫入順序（單行替換，ERR-056 登記冊引用行號不位移）；新增同秒回歸測試；版本 0.27.8；runbook 補記。原因：開發機趨勢 f-19 測試交易（BTCUSDT-28620601354）開倉 `20ca9096` 與平倉 `1e794fad` 同在 2026-10-06T09:37:53Z 排入，平倉隨機編號較小排前，先送被回 trade_id_not_found、連 12 次後停放（ERR-056），開倉 10:00:09 才送出，該筆帳本更正 close_not_confirmed 重試 510 次。

## 審閱者標明的界限

- 新順序＝「成功持久化入列的順序」，不是多程序呼叫開始時間；candidate 在取得鎖之前建立，程序 A 先建立較晚入列時檔案順序仍是 B→A。消費端仍須保證同筆交易的 open 先入列。
- 舊檔若檔案行序與時間順序不同，送出順序會改（runbook 已揭露）；沒有稽核所有策略的歷史 outbox。
- 已 REJECTED 的 close 不會因升版復活；close_not_confirmed 重試未修。PASS 不代表歷史資料已修、各策略已釘版或部署。
- 新測試是全域 FIFO（open、close 用不同 trade_id），不是同 trade_id 的接收端整合測試；審閱者以原文判斷還原修正會失敗，未自跑 mutation test。

## 教訓

- 測試裡早就有 `_ticking_clock` 註解寫明「同秒會被隨機編號排序」，是繞過而不是修掉；看到測試為了避開某個行為而特別處理時，要追問那個行為在正式程式裡會不會發生。

## 隔離聲明

本 PR 只動共用庫佇列排序、測試、版本與 runbook；沒有下單、保護單、帳本寫入或部署變動。審閱者只讀 GitHub 與 PR 留言；開發端讀開發機佇列檔為唯讀。
