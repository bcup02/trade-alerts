# 正式機搬到 Oracle 的搬家計畫（f-2c，草稿）

> 狀態：**草稿，等使用者審**。本文件只是計畫，任何一步正式機動作都要先問使用者。
> 對應進度頁項目：f-2（正式機搬到 Oracle 永久免費主機）。用詞照 `src/trade_alerts/catalog/fleet-glossary.json`。
> 2026-09-29 修訂：依首審 BLOCK 意見改寫——各部署腳本的實際啟動行為、逐檔搬遷清單、舊機先停用再啟動新機、
> 真倉開關最後才打開、退回改成先凍結再人工裁決；並補上「Oracle 先搬、GitHub 後搬、改用部署金鑰」的順序與閒置回收風險。

## 1. 為什麼要搬、搬去哪

- GCP 免費體驗 2026-12-06 到期（進度頁 f-9），到期沒處理正式機會被停掉。
- Oracle 東京已有一台永久免費 ARM 主機，**12/6 之前要完成切換**，並留至少一週緩衝。

| 項目 | 現在的正式機 | Oracle 新主機 |
|---|---|---|
| 名稱 | trading-main（GCP） | fleet-prod-tokyo |
| 規格 | e2-medium（2 vCPU／3.8GB，x86） | 2 核心／12GB，ARM（Ampere A1） |
| 系統 | Ubuntu、Python 3.12.3、時區 Asia/Tokyo、swap 512MB | Ubuntu 24.04、Python 3.12.3、時區目前 UTC、沒有 swap |
| 對外 IP | GCP 配的 IP | 保留 IP `161.33.186.220`（不會因重開機改變） |
| 費用 | 12/6 後付費 | 免費額度內（A1 每月 1,500 核心小時＋9,000 GB 小時＝一台 2 核心／12GB） |

## 2. 跟 GitHub 搬家的先後順序（使用者 2026-09-29 同意）

- **Oracle 先搬，不等 GitHub 搬家**。ECP 進度表（`AI-for-column/Engineering-Control-Plane` `PROJECT_STATUS.md`）
  把四支真倉策略排在 ECP-6C 最後一批，前面還有 ECP-4C 啟用、ECP-6B 與四個專案；12/6 前輪到策略的機會很低（推測，
  文件沒寫日期）。
- **新主機用每個 repo 各一把唯讀部署金鑰取碼**（共 10 把：8 個 repo＋Binance、MEXC 兩個交易所工具程式）。
  部署金鑰綁在 repo 上，repo 轉到新組織時會跟著走；GitHub 會把舊網址轉到新位置，搬完再把新主機的 remote 改成新網址。
- **兩件事不排在同一週**：換主機與換 GitHub 位置都會影響部署，同時進行出事時分不出原因。

## 3. 已經驗證過的事（2026-09-29）

- **ARM 能裝、測試能過**：8 個 repo 照各自 CI 指令在新主機安裝、跑測試全過（共用程式庫 381、動能 774、趨勢 522、
  加密 196、競賽 377、維運通知 143、Telegram 遙控 64、LINE 查詢 218）。
- **交易所連得到**：Binance（正式、模擬倉、測試網）與 MEXC 公開端點延遲 0.04–0.15 秒、沒被擋地區。
- **下單流程走得通**：用模擬倉金鑰從新主機掛單→用自訂編號查單→撤單（合約、現貨各一次，都沒成交）；MEXC 用開發機
  的金鑰只讀查帳戶與持倉成功。**正式機的 MEXC 金鑰（加密策略）還沒在新主機驗證**，放在階段 C 的啟動前檢查。
- **固定 IP**：已換成保留 IP，交易所 IP 白名單之後綁 `161.33.186.220`。

## 4. 正式機盤點結果（2026-09-29，唯讀）

1. **服務**：四支策略主程式、各自 5～7 個定時服務、`clock-health`、維運通知、Telegram 遙控、LINE 查詢，外加 LINE
   進站通道 `seykota-cloudflared`。沒有失敗的服務。docker 沒在用（`/opt/containerd` 是殘留，不搬）。
2. **開機自動啟動**：動能、趨勢、加密三支主程式、LINE 查詢、Telegram 遙控、LINE 進站通道都是 `enabled`；
   競賽策略主程式由它的每日定時服務觸發；維運通知與 `clock-health` 是定時服務。**舊機重開就會自己恢復交易**，
   所以切換時一定要先停用（disable）而不只是停止（stop）。
3. **設定檔**：各 `.env` 的變數名稱跟開發機相同（只比名稱、沒看值）。
4. **資料量很小**：帳本＋狀態合計約 7.5MB（動能 7.1MB，其他都在 100KB 以下）。
5. **四支策略都是真倉**（`STRATEGY_MODE=LIVE_ONLINE`、`DRY_RUN_ONLY=0`）。
6. **程式來源**：正式機家目錄有 8 個 repo 的 clone，用 `gh` 登入的 GitHub 帳號取碼，部署腳本在正式機本機執行。
7. **LINE 進站**：LINE 後台 webhook 走 `seykota-admin.deepsoultouch.com` → Cloudflare 通道 → 本機 `127.0.0.1:8830`
   （LINE 查詢）。通道憑證跟著搬，LINE 後台網址不用改。**同一條通道兩台同時執行時，Cloudflare 會把請求分給兩台**。
   通道程式是手動裝在 `/usr/local/bin/cloudflared`，不在任何部署腳本裡。
8. **其他手動設定**：時區 Asia/Tokyo、swap 512MB；沒有 cron、防火牆（ufw）沒開。

## 5. 各部署腳本的實際啟動行為（正式機分支，2026-09-29 讀原始碼）

| repo（正式機分支 commit） | 首次安裝的真倉開關 | 裝完會不會自己啟動 |
|---|---|---|
| 動能 `43be152` | 紙上模擬＋`DRY_RUN_ONLY=1` | 主程式設成開機啟動（`enable`）但不當場啟動；定時服務要 `START_SERVICE=1` 且設定檔已存在才啟動 |
| 趨勢 `3e3b6f7` | 離線（OFFLINE）＋`DRY_RUN_ONLY=1` | 同上（主程式 `enable`；`START_SERVICE=1` 才啟動） |
| 加密 `1efbdc0` | 紙上模擬＋`DRY_RUN_ONLY=1` | 同上 |
| 競賽 `9559897` | 離線（OFFLINE）＋`DRY_RUN_ONLY=1` | **會**：6 個定時服務（含每日調整）一律 `enable --now`，並立刻跑一次報告發布 |
| 維運通知 `01308c7` | — | **會**：`ops-notify.timer`、`clock-health.timer` 立刻啟動並各跑一次 |
| Telegram 遙控 `87c6272` | — | **會**：`ops-control.service` 立刻啟動（有憑證就開始收 Telegram 訊息） |
| LINE 查詢 `90dfab2` | — | **會**：服務立刻啟動（只監聽本機；通道沒開就收不到 LINE） |

因此計畫**不寫「裝好先不啟動」**，而是：裝完之後立刻把每支的全部服務與定時服務**停止並停用**，
再逐項讀回（`systemctl is-active`／`is-enabled` 全部是 inactive／disabled）才算階段 A 完成。
開關檔一律用 `grep` 讀回確認，不靠記憶。

## 6. 搬遷清單（階段 C 逐項勾核；反向退回也用同一份）

路徑都來自正式機的設定檔與服務設定（`ReadWritePaths`）。權限、擁有者照舊機原樣（`rsync -a`），複製後逐檔比對 sha256。

| 服務 | 要複製的路徑 |
|---|---|
| 動能 | `/opt/mexc-4h-momentum-trailing-stop/audit/`、`/opt/mexc-4h-momentum-trailing-stop/state/`、`/etc/mexc-momentum/momentum.env`、`/var/lib/mexc-4h-momentum-operations/`、`/var/lib/mexc-momentum-control/` |
| 趨勢 | `/opt/ed-seykota-systematic-trend-following/audit/`、`…/state/`、`…/logs/`、`/etc/seykota/seykota.env`、`/var/lib/seykota-operations/`、`/var/lib/portfolio-query/seykota-btcusdt-4h/` |
| 加密 | `/opt/my-crypto-bot/audit/`、`/opt/my-crypto-bot/state/`、`/etc/my-crypto-bot/my-crypto-bot.env`、`/var/lib/my-crypto-bot-operations/` |
| 競賽 | `/opt/btc-bull-market-competition/audit/`、`…/state/`、`…/logs/`、`/etc/btc-competition/btc-competition.env`、`/var/lib/btc-competition-operations/`、`/var/lib/portfolio-query/btc-bull-competition/` |
| 維運通知 | `/etc/ops-notify/ops-notify.env`、`/var/lib/ops-notify/`（已送紀錄；不搬會把舊通知重送一次） |
| Telegram 遙控 | `/etc/ops-control/ops-control.env`、`/var/lib/ops-control/`（Telegram 讀取位置） |
| LINE 查詢 | `/etc/portfolio-query/portfolio-query.env`、`/var/lib/portfolio-query/`（整個目錄，含上面兩支策略寫的子目錄） |
| LINE 進站通道 | `/etc/seykota/cloudflared.yml`、`/etc/seykota/<通道編號>.json`、`seykota-cloudflared.service`、`seykota-admin` 帳號 |
| 帳號與群組 | 維運通知加入四支策略的群組；Telegram 遙控加入動能策略的群組（照舊機 `id` 輸出） |

## 7. 切換步驟

**原則**：同一時間只能有一台在交易；新機啟動前，舊機必須已經「停止＋停用＋讀回確認」；真倉開關最後才打開；
每一階段開始前都先問使用者。

### 階段 A：新主機準備（不影響正式機）

1. 設好 10 把唯讀部署金鑰，clone 8 個 repo（策略與維運切到正式機分支，共用程式庫用 main），記下每個 commit。
2. 時區改 Asia/Tokyo、加 2GB swap；時鐘同步已確認正常。
3. 逐支跑部署腳本（不設 `START_SERVICE`、不放任何 `.env`），交易所工具程式用本機 clone（`*_SOURCE` 參數）。
4. 裝完**立刻**：`systemctl disable --now` 每支的全部服務與定時服務（第 5 段所列），讀回全部 inactive／disabled。
5. 讀回四支的開關檔：都是 `DRY_RUN_ONLY=1`，`STRATEGY_MODE` 為 OFFLINE 或紙上模擬。
6. 建服務帳號的跨群組設定、`seykota-admin` 帳號；裝 ARM 版 `cloudflared`，**不放通道憑證、不啟用**。
7. `cloudflared` 與跨群組設定補進 LINE 查詢／各 repo 的部署腳本（另開 PR，這次搬家範圍內要做完，不留手動步驟）。

### 階段 B：紙上模擬陪跑 1～2 天（不影響正式機）

1. **不放任何真倉金鑰**。四支策略維持 `DRY_RUN_ONLY=1`、紙上模擬；需要帳戶資料的部分用模擬倉（DEMO）金鑰或留空。
2. **只啟動**四支策略主程式與它們讀行情的定時服務；**不啟動**：Telegram 遙控、LINE 查詢、LINE 進站通道、
   維運通知、Google 表寫入、修復機器人。
3. 比對兩台同一根 K 棒算出的進出場訊號是否一致；記下 CPU／記憶體用量（第 9 段閒置回收評估要用）。
4. 陪跑結束：`systemctl disable --now` 全部，刪掉陪跑產生的帳本與狀態（新主機回到階段 A 結束的樣子），讀回確認。

### 階段 C：正式切換（要挑時間）

**C-0 挑時間與前置檢查**（全部通過才往下）
- 避開動能／趨勢 4 小時 K 棒收盤前後、競賽每日調整（08:10 台北）。
- 在舊機唯讀查四支的持倉與交易所掛單，逐筆記錄：有持倉的，確認交易所上有沒有獨立生效的保護單（停損／移動停損）。
  **沒有獨立保護單的持倉就不切換**，等平倉或改天。切換期間會漏掉移動停損的調整，這一點在紀錄裡寫明。
- 記下舊機四支開關檔的原始內容（退回時要用）。

**C-1 凍結舊機**
1. 停止並停用舊機全部服務與定時服務（第 4 段第 1 點的清單，含 LINE 進站通道）：`systemctl disable --now …`。
2. 讀回：全部 `inactive` 且 `disabled`；`systemctl list-timers` 沒有機隊的定時服務；沒有機隊的 Python 程序。
3. 舊機四支的開關檔改成 `DRY_RUN_ONLY=1`（多一道保險：就算有人手動啟動也不能下真單），讀回確認。
   **這一步沒有全部讀回通過，就不准進行 C-2。**

**C-2 複製與核對**
1. 照第 6 段清單逐項從舊機複製到新主機（開關檔複製的是 C-1 改過、`DRY_RUN_ONLY=1` 的版本）。
2. 兩邊逐檔 sha256 比對，全部一致才往下。
3. 新主機放入通道憑證與設定，但先不啟動。

**C-3 新主機啟動前檢查（仍然鎖住真倉）**
1. 用正式機的金鑰做只讀查詢（Binance 合約／現貨、MEXC 合約）：簽章通過、餘額與持倉跟 C-0 記錄一致。
2. 手動跑一次四支的對帳：帳本對交易所一致、零錯誤。有任何不一致就停，回到第 8 段「退回」。

**C-4 逐支打開真倉並啟動**
1. 一次一支：把該支開關檔改回 C-0 記下的原值（`LIVE_ONLINE`、`DRY_RUN_ONLY=0`），讀回確認 → 啟用並啟動該支的服務與
   定時服務 → 看第一輪日誌與對帳正常，才換下一支。
2. 啟用維運通知、`clock-health`、LINE 查詢、LINE 進站通道、Telegram 遙控。
3. 用 LINE 查詢、Telegram 遙控各實際操作一次；`systemctl --failed` 為空。

### 階段 D：穩定後

1. 觀察一週：每天看對帳狀態、服務失敗、通知是否正常。
2. 交易所 API 金鑰綁 IP 白名單 `161.33.186.220`（使用者在交易所後台設定）。
3. 更新文件、記憶、登記冊裡所有「正式機＝trading-main」的地方。
4. 舊機維持凍結（停用＋`DRY_RUN_ONLY=1`）並停機，硬碟保留到 12/6 前；確定不需要退回再刪除。

## 8. 出事怎麼退回

- **階段 A、B**：舊機完全沒動，停用新主機全部服務即可。
- **階段 C 在 C-4 之前**：新主機還沒下過真單。停用新主機全部服務 → 舊機開關檔改回 C-0 記下的原值 → 舊機重新啟用服務。
- **C-4 之後**（新主機已經用真倉跑過）：
  1. **凍結兩台**：新主機比照 C-1 停止＋停用＋`DRY_RUN_ONLY=1`，讀回確認；舊機維持凍結。
  2. 用第 6 段同一份清單把新主機的狀態**整份**複製回舊機（不是只複製新增部分），逐檔 sha256 比對。
  3. 在舊機手動跑四支對帳；帳本對交易所一致、事件日誌與維運通知已送紀錄沒有重複或缺漏，才依 C-4 的方式逐支打開舊機。
  4. **任何一項對不上，兩台都保持停止，由使用者人工裁決**，不直接重啟任何一台。

## 9. 閒置回收風險

- Oracle 官方免費額度頁：Always Free 主機若連續 7 天 CPU（95 百分位）、網路、記憶體（A1）使用率都低於 20%，
  可能被回收。官方文字只寫「Always Free 主機」，**沒寫升級成隨用隨付的帳戶是否適用**。
- 機隊很省資源：正式機現在記憶體約 0.9GB，放到 12GB 不到 10%；所以就算搬上來也可能被判定閒置。
- 應對：階段 B 量實際用量；向 Oracle 確認隨用隨付帳戶是否適用；確認前，從開發機定時檢查新主機是否在線，
  被停機時能立刻知道並依第 8 段退回。

## 10. 開發機怎麼辦

Oracle 免費額度只夠一台，給正式機用。開發機（trading-dev，GCP）12/6 後的選項，請使用者決定：

1. 續留 GCP、改付費（粗估每月約 35 美元，以 GCP 價格試算器為準）。
2. 換到別的便宜主機。
3. 不另外開開發機，只在本機開發（會少掉「先上開發機觀察」這一關，不建議）。

## 11. 使用者要做的事

- 審這份計畫，決定開發機去留（第 10 段）。
- 階段 A：在 10 個 repo 的 GitHub 設定頁貼上部署金鑰（Claude 會列出每一把公開金鑰與設定頁網址）。
- 階段 B、C、D 每一步開始前再確認一次。
- 階段 D 在 Binance、MEXC 後台設 IP 白名單。
