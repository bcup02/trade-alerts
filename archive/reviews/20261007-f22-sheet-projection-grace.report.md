# Perplexity 審閱歸檔 — 帳本↔Google 表對帳：剛開／剛平、還在等同步的交易不算對不上（PR #138，v0.27.7，f-22）

- **Repo**：bcup02/trade-alerts
- **PR**：#138，最終 head `4d69977df85302afd23359e3ecbe6f6963f36e01`，base `f01c07d6942486789646d418ee1b3f1213129789`（main），squash 合併為 `0b15a28`，tag `v0.27.7`
- **審閱者**：Perplexity — 兩輪：首審 head `c8709dc` **BLOCK**（B1）→ 複審 head `4d69977` **PASS**
- **CI**：pytest = success（最終 run `37586179469`；689 passed，baseline 674，+15）

## 做了什麼

`sheet_ledger_compare` 新增 `projection_grace_seconds`（預設 3600）：帳本新開（`SHEET_MISSING_ROW`）或新平（`SHEET_MISSING_CLOSE`）不到寬限、表上還沒有的交易，記為資訊類 `projection_pending`（`divergence=False`），不翻轉判定、不觸發 ERR-044；超過寬限、事件時間讀不出來、或比對帳時鐘晚超過 5 分鐘的壞時間，一律照舊 DIVERGED；0 秒關閉寬限、文件形狀在沒有等待項目時不變。ERR-044 目錄文字、runbook、風險登記冊頁面同步，版本 0.27.7。原因：A1 動能 2026-10-05～06 的 7 輪 DIVERGED 讀數（5 次 LINE 告警）每一輪都是對帳比 Google 同步先讀表（證據在 PR 留言）。

## 審閱過程

首審 BLOCK（B1）：`_awaiting_projection` 只檢查年齡上限、沒要求年齡非負，未來 30 天的 open／close 事件時間會讓缺列永遠顯示 RECONCILED（審閱者用隔離重播重現，再過 61 分鐘仍如此）。修正：要求 −5 分鐘（時鐘抖動容許）≤ 年齡 ≤ 寬限；新增 6 個測試（未來 open／close、容許邊界、close 邊界、開倉時間未知退回平倉時間、老開倉＋新平倉整列缺失、等待中＋LEDGER_MISSING_ROW）；ERR-044 與 runbook 補上壞時間立刻算對不上。複審 PASS：審閱者用純函式重播 14 個情境（含容許邊界與 61 分鐘後）全符合，關閉寬限 13 個情境、沒有等待 11 個情境的完整 document 與原邏輯相同。

## 審閱者標明的界限

- 5 分鐘容許值是本輪新增的政策，不是 A1 實測出的時鐘抖動；仍有界。
- 重播是隔離函式／fixtures，不是原始 pytest suite 的 mutation run。
- 審閱者重播「預設寬限改 0」是 9 個測試失敗，不是 PR 內文寫的 5 個（5 是首審版本的數字）；runbook 已改正。
- runbook 原有「下一輪自己恢復」過度概括（#1、#4 下一輪仍 DIVERGED），已改成「同一或後續同步週期 CONFIRMED、對帳之後恢復」。
- PASS 不表示消費端已釘版或部署，也不授權合併、發 tag 或操作 A1。

## 教訓

- 新增的「寬限」類判斷，第一反應要問「時間欄位反方向（未來、0、負）會怎樣」；這次是審閱抓到，不是我先想到。
- 寫 PR 內文的測試數字時要註明是哪一版（首審版 5 個失敗，複審版 9 個）。

## 隔離聲明

本 PR 只動共用庫的對帳判定函式、測試、錯誤目錄文字、runbook 與產生頁；沒有下單、保護單、帳本寫入或部署變動。審閱者只讀 GitHub 與 PR 留言，沒有接觸實機；開發端在 A1 的動作都是唯讀（journalctl、systemctl、ssh 讀檔）。
