# Perplexity 審閱歸檔 — 共用對帳比對只拿濾掉紙上列的帳本配對接手成交（PR #119，v0.27.1）

- **Repo**：bcup02/trade-alerts
- **PR**：#119，head `c3a62668d30283abff847df4105d48eb1f9aacbd`，base `73b189bceee05cff91124a0bf1968fa6bd11c481`（main），squash 合併為 `139dc8b`
- **審閱者**：Perplexity — 一輪：首審 **PASS**
- **CI**：pytest = success（run `37283660729`；632 passed，起始 630）

## 做了什麼

`exchange_ledger_compare` 呼叫 `match_fills_to_adopted_events` 時改傳濾掉紙上列的 `real`，不再傳整份 `ledger_events`（對應 #95 審閱 F1 在趨勢策略 compare.py 的同類修正）。版本 0.27.1，runbook 加條目。新增 2 個測試：呼叫端判為紙上的列（DEMO、無 order_id、非乾跑來源、與成交完全吻合）不能解釋真實成交（拿掉修正會失敗）；同一列被判為真實時照常解釋。

## 審閱重點

- 配對、order_id、部位比較三處用同一份 `real`；沒有紙上列的輸入，輸出與 v0.27.0 完全一致。
- 審閱者拿掉修正重現第一個新測試失敗，並模擬動能預設 `is_paper_event`：無 order_id 的 DEMO 平倉被判紙上，結果 DIVERGED、成交 1002 留在清單——保守方向；是否讓動能認定原生停損平倉為真實，留給動能改釘 PR 另做實證。

## 審閱者標明的界限

- 保證只限 `exchange_ledger_compare`；獨立呼叫配對函式的消費端要自行確保候選列符合其紙上規則。
- 全量回歸以 CI 為準，審閱者沒有本地全量 pytest。「目前沒有策略走共用路徑」是開發端盤點，未獨立確認。
- PASS 不代表可部署或發 tag。

## 隔離聲明

審閱者唯讀；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或實機帳本。合併不代表任何主機部署。
