# Perplexity 審閱歸檔 — 登記冊：接手成交對帳上 A1 後改已做＋sources 換版（PR #127）

- **Repo**：bcup02/trade-alerts
- **PR**：#127，最終 head `3323752b97f90c28b1c6f0af72ecd5b39dd4ecf2`，base `0a9d194c263b4de3cd771b5f9af8824057ff2601`（main），squash 合併為 `1011468`
- **審閱者**：Perplexity — 兩輪：`78a2bf8` BLOCK（F1 部署時間把 JST 寫成台北）→ `3323752` **PASS**
- **CI**：pytest = success（最終 run `37301422425`；662 passed，無新增測試）

## 做了什麼

趨勢 #95、動能 #116／#118 部署 A1 正式機（新）後（趨勢 operations `5958bbf`、動能 `97f5ebb`；台北 18:56／18:57），登記冊 `reconcile.adopted_fills` 趨勢、動能改已做（證據綁 A1：`/opt` 檔案雜湊與 commit 相同、venv 共用庫版本與對帳檔 blob 與 tag 同檔、手動與排程對帳 RECONCILED、維運通知 notices=0、0 失敗單元，限制照實寫）；`sources` momentum `ce51083`→`97f5ebb`、seykota `ed50b1d`→`5958bbf`，既有 119 筆帶行號引用逐筆重定位（行號不變 95、改變 24、不一致 0，含所在函式比對）；ERR-008 說明改為已部署；移除無引用的 phase；`recent_changes` 兩個 completed＋一個 updated。

## 審閱過程

首審 BLOCK（F1）：兩個新 done 格寫「台北 19:56／19:57」，A1 journal 是 JST，台北應為 18:56／18:57。我同時查出更早的 #89 部署也有同樣錯誤：A1 journal 顯示 bot 重啟 JST 14:43＝台北 13:43，先前一路寫成台北 14:43（登記冊、ERR-008、進度頁、記憶）。已全部改為同時標台北／JST／UTC，並在記憶 feedback-use-taipei-time 加入這次再犯與換算規則。同輪處理審閱建議：趨勢 `latch.consecutive_failure_counter`、`SEY.RECONCILE_FAILED`、`SEY.RUNTIME_CYCLE_FAILED` 補「連續失敗只計非暫時性失敗」（引用 `bot.py:1599／:2282`，#89 語意）；重定位報告新增所在函式比對，多候選的 4 筆都在同一函式。

## 審閱者標明的界限

- 趨勢 venv 是共用庫 0.27.0：趨勢自己的 `compare.py` 已傳 real 並呼叫配對函式，措辭限定在這條實際呼叫路徑。
- A1 上這兩支沒有接手倉位，新路徑的實際觸發只在開發機與測試驗證過。
- 119 筆比對證明「文字與所在函式相同」，不等於周邊語意永遠不變；審閱者沒有重跑 render 或跨 repo verifier。
- `latch.restart_only_clear` 等舊 pending 理由（寫「還沒上正式機」）沒有逐項核對 A1，未改，另案。
- PASS 不授予合併後發布或部署權限。

## 隔離聲明

審閱者唯讀；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或實機帳本。A1 證據為開發端唯讀取得。
