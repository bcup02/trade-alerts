# 正式機搬到 Oracle 的搬家計畫（f-2c）

- PR：[bcup02/trade-alerts#79](https://github.com/bcup02/trade-alerts/pull/79)，squash 合併 `0184e61`（base `5a6fa29`）
- Perplexity：五輪——首審 **BLOCK**（head `a5c33fe`）→ 複審 **BLOCK**（`2e48f83`）→ 複審 **BLOCK**（`ed35ae5`）→
  複審 **BLOCK**（`743d5e0`）→ 複審 **PASS**（`6f60d4d`）
- CI：pytest 381 passed（最後一輪 run 36548355380）

## 內容

新增 `docs/guides/oracle-migration-plan.md`（純文件，不用部署）：正式機 trading-main（GCP）搬到 Oracle 東京 A1
fleet-prod-tokyo 的計畫。Oracle 先搬、GitHub（ECP-6C）後搬、每個 repo 各一把唯讀部署金鑰；正式機唯讀盤點；
各部署腳本實際啟動行為；54 個 unit 的完整 manifest 與讀回 gate；安裝前擋住自動啟動（4 支部署腳本補 `START_SERVICE=0`
為階段 A 前置 PR）；陪跑改成新主機暫代開發機；完整搬遷路徑、快照＋`--delete`＋完整檔案集合雜湊比對；
退回前一律重查交易所、不一致兩台都停由使用者裁決；閒置回收風險。

## 審閱重點

1. 首審：舊機要在新機啟動前先停用（不只停止）；競賽與維運三件部署腳本一裝就啟動，「裝好不啟動」不成立；
   缺逐檔清單；退回只複製新增檔案會分叉；停損保護說法過度。
2. 複審一：凍結名單不是可逐項核對的集合；裝完才停用擋不住安裝時的執行；OFFLINE 陪跑沒有進入紙上模擬的步驟；
   `rsync` 不清目的端舊檔、退回前沒重查交易所。
3. 複審二：名單用基底名、與 `systemctl list-unit-files` 輸出不同構。改成正式機逐字輸出的 54 個 unit＋可執行 gate。
4. 複審三：審閱誤算競賽 unit 為 13（實際 12，`btc-competition-daily.timer` 觸發的是 `btc-competition-bot.service`），
   開發端驗算後維持 47，但依建議逐字列出子清單與集合驗證；複審四 PASS 並確認 47 正確。

教訓：計畫裡的「清單」要跟實際工具輸出同構、可機械比對，不能只寫類別；部署腳本行為要讀原始碼，不能假設一致。

## 隔離聲明

審閱只讀 GitHub；開發端讀正式機均為唯讀（使用者 2026-09-29 授權），沒有改任何主機、服務、交易所或帳本。
