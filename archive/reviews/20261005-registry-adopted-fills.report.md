# Perplexity 審閱歸檔 — 登記冊新增「接手倉位成交配對」一列（PR #125）

- **Repo**：bcup02/trade-alerts
- **PR**：#125，最終 head `fb7180d659c0d89875d241dc445ce8553340bfe5`，base `3c6c2f229b582d9480c02c48db52b2c42b2ec126`（main），squash 合併為 `5d26f61`
- **審閱者**：Perplexity — 兩輪：`4cbe026` BLOCK（競賽列理由超出證據）→ `fb7180d` **PASS**
- **CI**：pytest = success（最終 run `37298609633`；662 passed，無新增測試）

## 做了什麼

一致性登記冊新增 capability 列 `reconcile.adopted_fills`（t4 系列：共用庫 v0.27.0–v0.27.3）與兩個 phase（`adopted-fills`、`x3-crypto-binance`）；`recent_changes` 換成這次的單一 added 項；重新產生 `fleet-rollout-register.html`。動能、趨勢＝待辦（開發機已驗證 RECONCILED、A1 正式機（新）未部署）；加密＝待辦（development 的 `mexc_futures_bot.py` 兩處寫沒有訂單編號的 `position_recovered`，對帳是舊版共用庫 v0.15.0；換 Binance x3 時升級）；競賽＝目前列為不適用。

## 審閱過程

1. 首審 BLOCK：競賽列寫了「帳本的成交列都是自己下單的紀錄，沒有這種對不上的情況」，附件證據只是對一個 commit 的 `src` 搜尋兩個關鍵字，撐不起全面聲明。修正：理由綁定日期、commit、目錄與方法，明講未逐行盤點全部帳本寫入路徑、新增接手寫法要重審；加密理由補上 development 7a59081、operations 未另查，並把「升級後具備」改成目標。
2. 複審 PASS：JSON 與生成頁四處文字逐項相同；其餘舊列、sources、catalog、風險頁都未動。

## 審閱者標明的界限

- n/a 只代表現有明示的有限查證與重審條件，不是證明競賽所有帳本寫入路徑都不適用。
- 加密「升級後具備」是 x3 目標，仍需整合與端到端驗證（附件沒有顯示 `execution_mode` 等配對必要欄位是否由帳本補入）。
- 沒有讀 operations 分支，也沒有把 pending 理由當成正式機認證。

## 隔離聲明

審閱者唯讀；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或實機帳本。合併不代表任何主機部署。
