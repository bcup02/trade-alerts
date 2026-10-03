# Perplexity 審閱歸檔 — f-16d：ERR-056 找不到開倉列的平倉被停放（錯誤清單＋登記冊）

- **Repo**：bcup02/trade-alerts
- **PR**：#109，最終 head `aa0356fecad31ad1126510fd1dfc3bf55d631074`，base `e266a673ba406f112e0ab30c29883582f74e392e`（main），squash 合併為 `648b8bf`
- **審閱者**：Perplexity — 兩輪：首審 `BLOCK`（head `0be96270413f8d9ec3649e0aa5e85a254fb9d7b5`）、複審 **`PASS`**
- **CI**：pytest = success（首審 run `37095078193`、複審 run `37096005751`；456 passed）

## 做了什麼

錯誤清單新增 ERR-056 `FLEET.PROJECTION_ORPHAN_CLOSE_PARKED`（R1，MECHANICAL；`error_ids_issued` 55→56）；一致性登記冊新增對應列與 phase `f-16`（動能、趨勢、競賽待辦，加密不適用）；`docs/fleet-error-catalog.md` 補表格列；兩張登記冊頁面重新產生。沒有改任何程式碼。

## 審閱過程

- 首審 BLOCK：**原因是審閱工具讀不到檔案正文（SOP、完整 JSON、底層實作），證據未取得，不是找到缺陷**；六項逐項結論在已讀到的 diff 範圍內都沒有發現錯誤。另提一則非阻擋文案：`human_action` 先說「才需要補開倉列」又列出忽略清單選項，讀起來矛盾。
- 開發端處理：改寫 `human_action` 為「先確認交易存在，再二選一」；自查發現登記冊把競賽策略的共用庫版本寫錯（寫 v0.24.2，實際開發主幹 v0.25.0、正式機 v0.23.0），一併更正；複審指令把審閱者讀不到的證據（ERR 編號 1–56 連續、`projection_outbox.py:33、267–269`、此 head 的 `--check` 與 `verify_registry_evidence.py` 結果）直接貼進去。
- 複審 PASS：兩個追加 commit 合計 4 檔各 1 行；審閱者聲明 SOP 仍讀不到、以請求內證據加 PR diff 為審閱基準；未獨立重跑 `--check`。

## 已知待辦（合併後發現，未在本 PR 處理）

登記冊把加密策略兩格寫成「不適用」，理由是「沒有 Google 表同步佇列」。查證（`docs/google-sheet-recording-rules.md` 第 12 行、`my-crypto-bot` 的 src 沒有投影程式）：現在確實沒有，但文件寫的是「還沒升級共用庫」（歸第 8 關 8c／g1-6），所以嚴格說是「還沒有」而不是「永遠不適用」。升級共用庫接上投影時要改成待辦（第 8 關）；已登記進度頁，下一次動登記冊時一併改。

## 隔離聲明

審閱者唯讀；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或正式機帳本。本 PR 不用部署。
