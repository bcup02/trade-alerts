# 正式機搬到 Oracle 的搬家計畫（f-2c，草稿）

> 狀態：**草稿，等使用者審**。本文件只是計畫，任何一步正式機動作都要先問使用者。
> 對應進度頁項目：f-2（正式機搬到 Oracle 永久免費主機）。用詞照 `src/trade_alerts/catalog/fleet-glossary.json`。
> 2026-09-29 修訂：依首審 BLOCK 意見改寫——各部署腳本的實際啟動行為、逐檔搬遷清單、舊機先停用再啟動新機、
> 真倉開關最後才打開、退回改成先凍結再人工裁決；並補上「Oracle 先搬、GitHub 後搬、改用部署金鑰」的順序與閒置回收風險。
> 2026-09-29 二修（複審 BLOCK）：安裝前就不讓服務啟動（四支部署腳本補上只安裝選項）、陪跑改成「新主機暫代開發機」、
> 完整服務名單、完整路徑、退回時比對兩端完整檔案集合並先重查交易所。
> 2026-09-29 三修（第二次複審 BLOCK）：5.1 改成跟 `systemctl list-unit-files` 同格式的完整 manifest（含副檔名與凍結後預期狀態）與可執行的讀回 gate。

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
- **新主機用每個私有 repo 各一把唯讀部署金鑰取碼**（共 7 把：四支策略＋維運通知、Telegram 遙控、LINE 查詢；共用程式庫 trade-alerts 與 Binance、MEXC 兩個交易所工具程式是公開 repo，直接用 https 取）。2026-09-29 已設好：金鑰在新主機 `~ubuntu/.ssh/deploy/<repo>`，以 `github-<repo>` 主機別名取碼；實測 7 個都能讀、推送一律被 GitHub 以 read only 拒絕。
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

1. **服務**：完整名單見第 5.1 段（正式機 `systemctl list-unit-files` 實際輸出）。沒有失敗的服務。docker 沒在用
   （`/opt/containerd` 是殘留，不搬）。
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

因此**不能先裝再關**：有 4 支腳本一裝就會執行。做法是在安裝**之前**就擋住（見 5.2）。

### 5.1 完整服務名單（凍結、準備、陪跑都照這份逐一核對）

下面是正式機 2026-09-29 `systemctl list-unit-files` 的實際輸出（用下面同一個篩選條件取出、排序），共 54 個 unit：
30 個平常是 `enabled`、24 個是 `static`（由同名 timer 觸發的 service）。沒有 masked、generated 或其他類型的機隊 unit。

每一行是「unit 名稱　**凍結後**應有的 `systemctl is-enabled` 結果」；凍結後每一項的 `systemctl is-active` 都必須是 `inactive`。
平常 `enabled` 的凍結後要變成 `disabled`；`static` 的凍結後仍是 `static`（它沒有自己的開機啟動，靠 timer 觸發；timer 停用後就不會再跑）。

```text
btc-competition-bot.service static
btc-competition-daily.timer disabled
btc-competition-google-projection.service static
btc-competition-google-projection.timer disabled
btc-competition-portfolio-snapshot.service static
btc-competition-portfolio-snapshot.timer disabled
btc-competition-reconcile-fetch.service static
btc-competition-reconcile-fetch.timer disabled
btc-competition-report-publish.service static
btc-competition-report-publish.timer disabled
btc-competition-unrecorded-fill.service static
btc-competition-unrecorded-fill.timer disabled
clock-health.service static
clock-health.timer disabled
mexc-momentum-bot.service disabled
mexc-momentum-control-consumer.service static
mexc-momentum-control-consumer.timer disabled
mexc-momentum-funding-sync.service static
mexc-momentum-funding-sync.timer disabled
mexc-momentum-google-projection.service static
mexc-momentum-google-projection.timer disabled
mexc-momentum-portfolio-snapshot.service static
mexc-momentum-portfolio-snapshot.timer disabled
mexc-momentum-reconcile-fetch.service static
mexc-momentum-reconcile-fetch.timer disabled
mexc-momentum-repair-shadow.service static
mexc-momentum-repair-shadow.timer disabled
mexc-momentum-report-publish.service static
mexc-momentum-report-publish.timer disabled
my-crypto-bot-funding-sync.service static
my-crypto-bot-funding-sync.timer disabled
my-crypto-bot.service disabled
my-crypto-portfolio-snapshot.service static
my-crypto-portfolio-snapshot.timer disabled
my-crypto-reconcile-fetch.service static
my-crypto-reconcile-fetch.timer disabled
my-crypto-report-publish.service static
my-crypto-report-publish.timer disabled
ops-control.service disabled
ops-notify.service static
ops-notify.timer disabled
portfolio-query.service disabled
seykota-bot.service disabled
seykota-cloudflared.service disabled
seykota-google-projection.service static
seykota-google-projection.timer disabled
seykota-portfolio-snapshot.service static
seykota-portfolio-snapshot.timer disabled
seykota-reconcile-fetch.service static
seykota-reconcile-fetch.timer disabled
seykota-repair-shadow.service static
seykota-repair-shadow.timer disabled
seykota-report-publish.service static
seykota-report-publish.timer disabled
```

**凍結指令**（舊機 C-1、新主機安裝後、陪跑結束都用這個）：

```bash
systemctl disable --now btc-competition-daily.timer btc-competition-google-projection.timer btc-competition-portfolio-snapshot.timer btc-competition-reconcile-fetch.timer btc-competition-report-publish.timer btc-competition-unrecorded-fill.timer clock-health.timer mexc-momentum-bot.service mexc-momentum-control-consumer.timer mexc-momentum-funding-sync.timer mexc-momentum-google-projection.timer mexc-momentum-portfolio-snapshot.timer mexc-momentum-reconcile-fetch.timer mexc-momentum-repair-shadow.timer mexc-momentum-report-publish.timer my-crypto-bot-funding-sync.timer my-crypto-bot.service my-crypto-portfolio-snapshot.timer my-crypto-reconcile-fetch.timer my-crypto-report-publish.timer ops-control.service ops-notify.timer portfolio-query.service seykota-bot.service seykota-cloudflared.service seykota-google-projection.timer seykota-portfolio-snapshot.timer seykota-reconcile-fetch.timer seykota-repair-shadow.timer seykota-report-publish.timer
systemctl stop $(systemctl list-unit-files --no-legend --plain | awk '{print $1}' | grep -E '^(mexc-momentum|seykota|btc-competition|my-crypto|ops-notify|ops-control|portfolio-query|clock-health)')
```

**讀回 gate**（把上面的 manifest 存成 `fleet-units.manifest`；任何一行輸出都算 BLOCK，要停下來查）：

```bash
# 1) 實際 unit 集合必須與 manifest 完全相同（多或少任何一個都會印出 diff）
systemctl list-unit-files --no-legend --plain | awk '{print $1}' | grep -E '^(mexc-momentum|seykota|btc-competition|my-crypto|ops-notify|ops-control|portfolio-query|clock-health)' | sort > actual.txt
awk '{print $1}' fleet-units.manifest | sort | diff - actual.txt
# 2) 每一個 unit 的 is-enabled 必須等於 manifest，is-active 必須是 inactive
#    （masked、generated、linked、enabled、active、failed 等任何其他值都會印出 FAIL）
while read -r u want; do
  e=$(systemctl is-enabled "$u" 2>&1); a=$(systemctl is-active "$u" 2>&1)
  [ "$e" = "$want" ] && [ "$a" = "inactive" ] || echo "FAIL $u is-enabled=$e is-active=$a"
done < fleet-units.manifest
# 3) 沒有任何機隊 timer 排程、沒有機隊的 Python 程序
systemctl list-timers --all --no-legend | grep -E '(mexc-momentum|seykota|btc-competition|my-crypto|ops-notify|ops-control|portfolio-query|clock-health)' && echo FAIL-timers
pgrep -af '/opt/(mexc-4h-momentum-trailing-stop|ed-seykota-systematic-trend-following|my-crypto-bot|btc-bull-market-competition|ops-notify|ops-control|portfolio-query)/' && echo FAIL-procs
```

新主機安裝後的 unit 集合也必須與這份 manifest 相同（部署腳本裝出來的 unit 若多或少，同樣視為 BLOCK）。
階段 B 陪跑、C-4 啟動時，「允許啟動的 unit」都從這份 manifest 裡挑，寫成一份子清單後照同樣方式讀回。

### 5.2 安裝前就擋住自動啟動

1. **階段 A 之前先開 PR**：競賽、維運通知、Telegram 遙控、LINE 查詢四支的部署腳本，比照另外三支策略支援
   `START_SERVICE=0`（只安裝、設成停用、不啟動、不跑一次）。預設值維持現在的行為，所以開發機、正式機現有的部署方式不變；
   這是讓七支腳本行為一致的正式選項，不是過渡開關。照一般流程審閱、合併、進正式機分支。
2. 新主機只用**含這個選項的正式機分支 commit** 安裝，一律加 `START_SERVICE=0`；安裝前先讀該 commit 的腳本，
   確認所有 `systemctl start`／`enable --now`／`restart` 都在 `START_SERVICE=1` 條件內，否則不裝。
3. 第二道保險：安裝時新主機**還沒有任何 `.env` 設定檔與金鑰**（服務就算被誤啟動，也連不到 LINE、Telegram、
   Google 表，也沒有交易所金鑰），四支開關檔是部署腳本預設的 OFFLINE／紙上模擬＋`DRY_RUN_ONLY=1`。
4. 安裝後跑 5.1 的讀回 gate（零輸出），並查 `journalctl` 確認安裝期間沒有任何機隊服務執行過。

## 6. 搬遷清單（階段 C 逐項勾核；反向退回也用同一份）

路徑都來自正式機的設定檔與服務設定（`ReadWritePaths`）。權限、擁有者照舊機原樣（`rsync -a`），複製後逐檔比對 sha256。

| 服務 | 要複製的路徑（完整） |
|---|---|
| 動能 | `/opt/mexc-4h-momentum-trailing-stop/audit/`、`/opt/mexc-4h-momentum-trailing-stop/state/`、`/etc/mexc-momentum/momentum.env`、`/var/lib/mexc-4h-momentum-operations/`、`/var/lib/mexc-momentum-control/` |
| 趨勢 | `/opt/ed-seykota-systematic-trend-following/audit/`、`/opt/ed-seykota-systematic-trend-following/state/`、`/opt/ed-seykota-systematic-trend-following/logs/`、`/etc/seykota/seykota.env`、`/var/lib/seykota-operations/` |
| 加密 | `/opt/my-crypto-bot/audit/`、`/opt/my-crypto-bot/state/`、`/etc/my-crypto-bot/my-crypto-bot.env`、`/var/lib/my-crypto-bot-operations/` |
| 競賽 | `/opt/btc-bull-market-competition/audit/`、`/opt/btc-bull-market-competition/state/`、`/opt/btc-bull-market-competition/logs/`、`/etc/btc-competition/btc-competition.env`、`/var/lib/btc-competition-operations/` |
| 維運通知 | `/etc/ops-notify/ops-notify.env`、`/var/lib/ops-notify/`（已送紀錄；不搬會把舊通知重送一次） |
| Telegram 遙控 | `/etc/ops-control/ops-control.env`、`/var/lib/ops-control/`（Telegram 讀取位置） |
| LINE 查詢 | `/etc/portfolio-query/portfolio-query.env`、`/var/lib/portfolio-query/`（整個目錄，含趨勢寫的 `seykota-btcusdt-4h/` 與競賽寫的 `btc-bull-competition/`） |
| LINE 進站通道 | `/etc/seykota/cloudflared.yml`、`/etc/seykota/b919b953-8278-41c3-9e29-393baf564cb0.json`（通道憑證）、`seykota-cloudflared.service`、`seykota-admin` 帳號 |
| 帳號與群組 | 維運通知加入四支策略的群組；Telegram 遙控加入動能策略的群組（照舊機 `id` 輸出） |

**複製與核對方式**（正向、反向都一樣）：
1. 複製前，在**來源端**把上表全部路徑打包成一份唯讀快照（`tar`，附 sha256），留在兩台主機上，事後不改。
2. 目的端對應目錄先清空再複製（`rsync -a --delete`），不留目的端原有的舊檔。
3. 兩端各自產生「完整檔案清單＋每個檔案 sha256」（`find … -type f | sort` 後逐檔雜湊），**兩份清單要完全相同**
   （檔名集合一樣、內容一樣、沒有任何一邊多出來的檔案），才算複製完成。

## 7. 切換步驟

**原則**：同一時間只能有一台在交易；新機啟動前，舊機必須已經「停止＋停用＋讀回確認」；真倉開關最後才打開；
每一階段開始前都先問使用者。

### 階段 A：新主機準備（不影響正式機）

0. 先完成 5.2 第 1 點的四個部署腳本 PR，並進入正式機分支。
1. 用已設好的 7 把唯讀部署金鑰（私有 repo）與 https（公開 repo）clone 8 個 repo（策略與維運切到正式機分支，共用程式庫用 main），記下每個 commit。
2. 時區改 Asia/Tokyo、加 2GB swap；時鐘同步已確認正常。
3. 照 5.2 逐支安裝：`START_SERVICE=0`、**不帶任何 `*_SOURCE` 參數**（讓各策略照自己釘的版本從 GitHub 取共用程式庫與交易所工具程式；2026-09-29 曾用本機 main 的 clone 蓋掉釘選版本，Binance 工具 main 停在 0.2.1，動能因此起不來）。策略腳本會放一份與範例相同、不含金鑰的設定檔範本，這是預期行為。
4. 跑 5.1 的讀回 gate（零輸出），`journalctl` 確認安裝期間沒有機隊服務執行過。
5. 讀回四支的開關檔：都是 `DRY_RUN_ONLY=1`，`STRATEGY_MODE` 為 OFFLINE 或紙上模擬。動能、加密的腳本在全新主機會自己建立快照資料夾（動能 #106、加密 #53，2026-09-30 起）。
6. 帳號、跨群組設定與通道都由部署腳本建立（2026-09-29 已補進腳本：portfolio-query#25、ops-notify#29、ops-control#14）：先裝四支策略（建出策略群組），再裝維運通知、Telegram 遙控、LINE 查詢；LINE 進站通道用 `START_SERVICE=0 bash deploy/install_line_ingress.sh`（portfolio-query repo）裝 ARM 版 `cloudflared`（固定版本、比對校驗碼）與 `seykota-admin`，**不放通道憑證、不啟用**。
7. 只有含帳號密碼的設定檔與通道憑證仍是手動（階段 C 才搬）。

### 階段 B：新主機暫代開發機 1～2 天（不影響正式機）

用開發機已經在跑、已經驗證過的設定，讓新主機跑正式機分支的程式；開發機四支策略同時停下，避免兩台搶同一個模擬倉帳戶。

1. **開發機凍結四支策略**：用下面的「四支策略子清單」（5.1 manifest 的子集合，逐字取出、排序），在開發機跑 5.1 的凍結指令
   與讀回 gate（gate 的 manifest 換成這份子清單、集合比對的篩選條件換成 `^(mexc-momentum-|seykota-|my-crypto-|btc-competition-)`
   並排除 `seykota-cloudflared.service`），零輸出才往下。2026-09-29 已比對：開發機這些 unit 與正式機完全相同。

   子清單共 47 個：動能 15（主程式 1＋7 個 timer＋7 個同名 service）、趨勢 11（1＋5＋5）、加密 9（1＋4＋4）、
   競賽 12（主程式 1＋6 個 timer＋5 個同名 service；`btc-competition-daily.timer` 觸發的是 `btc-competition-bot.service`，
   沒有 `btc-competition-daily.service`）。集合關係可機械驗證：這份子清單的每一行都必須原樣出現在 5.1 manifest
   （`grep -vxFf 5.1-manifest 子清單` 零輸出），且 5.1 manifest 中符合上述篩選條件的行數必須正好 47。

   ```text
   btc-competition-bot.service static
   btc-competition-daily.timer disabled
   btc-competition-google-projection.service static
   btc-competition-google-projection.timer disabled
   btc-competition-portfolio-snapshot.service static
   btc-competition-portfolio-snapshot.timer disabled
   btc-competition-reconcile-fetch.service static
   btc-competition-reconcile-fetch.timer disabled
   btc-competition-report-publish.service static
   btc-competition-report-publish.timer disabled
   btc-competition-unrecorded-fill.service static
   btc-competition-unrecorded-fill.timer disabled
   mexc-momentum-bot.service disabled
   mexc-momentum-control-consumer.service static
   mexc-momentum-control-consumer.timer disabled
   mexc-momentum-funding-sync.service static
   mexc-momentum-funding-sync.timer disabled
   mexc-momentum-google-projection.service static
   mexc-momentum-google-projection.timer disabled
   mexc-momentum-portfolio-snapshot.service static
   mexc-momentum-portfolio-snapshot.timer disabled
   mexc-momentum-reconcile-fetch.service static
   mexc-momentum-reconcile-fetch.timer disabled
   mexc-momentum-repair-shadow.service static
   mexc-momentum-repair-shadow.timer disabled
   mexc-momentum-report-publish.service static
   mexc-momentum-report-publish.timer disabled
   my-crypto-bot-funding-sync.service static
   my-crypto-bot-funding-sync.timer disabled
   my-crypto-bot.service disabled
   my-crypto-portfolio-snapshot.service static
   my-crypto-portfolio-snapshot.timer disabled
   my-crypto-reconcile-fetch.service static
   my-crypto-reconcile-fetch.timer disabled
   my-crypto-report-publish.service static
   my-crypto-report-publish.timer disabled
   seykota-bot.service disabled
   seykota-google-projection.service static
   seykota-google-projection.timer disabled
   seykota-portfolio-snapshot.service static
   seykota-portfolio-snapshot.timer disabled
   seykota-reconcile-fetch.service static
   seykota-reconcile-fetch.timer disabled
   seykota-repair-shadow.service static
   seykota-repair-shadow.timer disabled
   seykota-report-publish.service static
   seykota-report-publish.timer disabled
   ```

2. **複製開發機的設定到新主機**：四支策略的 `.env` 與開關檔，照開發機現況是 `STRATEGY_MODE=DRY_RUN_ONLINE`、
   `DRY_RUN_ONLY=1`（這是紙上模擬上線；動能、趨勢、競賽會在**模擬倉**帳戶下單、加密沒有金鑰），**不放任何真倉金鑰**。
   複製後把 `.env` 裡 LINE、Telegram、Google 表的設定清空，讀回確認。開關檔用 `grep` 讀回確認四支都是上述兩個值。
3. **只啟動**四支策略主程式與它們的對帳、快照定時服務；**不啟動**：Google 表寫入、修復機器人、維運通知、
   Telegram 遙控、LINE 查詢、LINE 進站通道。允許啟動的 unit 先寫成子清單（從 5.1 manifest 挑）；啟動後，子清單內的 timer／常駐服務讀回 `enabled`＋`active`，manifest 其餘每一項仍照 5.1 gate 讀回 `disabled`／`static`＋`inactive`。
4. 觀察：每一輪都正常、跟開發機平常的行為一致；動能、趨勢同一根 K 棒的判斷跟正式機一致；記下 CPU／記憶體用量
   （第 9 段閒置回收評估要用）。
5. 結束：新主機用 5.1 凍結指令全部停用、讀回 gate 零輸出；刪掉陪跑產生的帳本、狀態與 `.env`（新主機回到階段 A 結束的樣子）；
   開發機四支策略重新啟用、讀回、手動跑一輪確認正常。

### 階段 C：正式切換（要挑時間）

**C-0 挑時間與前置檢查**（全部通過才往下）
- 避開動能／趨勢 4 小時 K 棒收盤前後、競賽每日調整（08:10 台北）。
- 在舊機唯讀查四支的持倉與交易所掛單，逐筆記錄：有持倉的，確認交易所上有沒有獨立生效的保護單（停損／移動停損）。
  **沒有獨立保護單的持倉就不切換**，等平倉或改天。切換期間會漏掉移動停損的調整，這一點在紀錄裡寫明。
- 記下舊機四支開關檔的原始內容（退回時要用）。

**C-1 凍結舊機**
1. 在舊機跑 5.1 的凍結指令（54 個 unit 全部，含 LINE 進站通道）。
2. 在舊機跑 5.1 的讀回 gate，必須零輸出（集合相同、每項 is-enabled 符合 manifest、全部 inactive、沒有機隊 timer 與程序）。
3. 舊機四支的開關檔改成 `DRY_RUN_ONLY=1`（多一道保險：就算有人手動啟動也不能下真單），讀回確認。
   **這一步沒有全部讀回通過，就不准進行 C-2。**

**C-2 複製與核對**
1. 照第 6 段的方式複製（來源快照 → `rsync -a --delete` → 兩端完整檔案清單＋sha256 完全相同）；
   開關檔複製的是 C-1 改過、`DRY_RUN_ONLY=1` 的版本。
2. 兩端清單不完全相同就停，回到第 8 段。
3. 新主機放入通道憑證與設定（`/etc/seykota/cloudflared.yml`、憑證 json 640 root:seykota-admin），但先不啟動。

**C-3 新主機啟動前檢查（仍然鎖住真倉）**
1. 用正式機的金鑰做只讀查詢（Binance 合約／現貨、MEXC 合約）：簽章通過、餘額與持倉跟 C-0 記錄一致。
2. 手動跑一次四支的對帳：帳本對交易所一致、零錯誤。有任何不一致就停，回到第 8 段「退回」。

**C-4 逐支打開真倉並啟動**
1. 一次一支：把該支開關檔改回 C-0 記下的原值（`LIVE_ONLINE`、`DRY_RUN_ONLY=0`），讀回確認 → 啟用並啟動該支的服務與
   定時服務 → 看第一輪日誌與對帳正常，才換下一支。
2. 啟用維運通知、`clock-health`、LINE 查詢、Telegram 遙控；LINE 進站通道用 `LINE_INGRESS_CUTOVER=old-connector-stopped bash deploy/install_line_ingress.sh` 啟動——這個宣告只能在 C-1 讀回確認舊機通道已停止並停用之後使用，腳本無法遠端驗證舊機，沒有宣告會拒絕啟動。
3. 用 LINE 查詢、Telegram 遙控各實際操作一次；`systemctl --failed` 為空。

### 階段 D：穩定後

1. 觀察一週：每天看對帳狀態、服務失敗、通知是否正常。
2. 交易所 API 金鑰綁 IP 白名單 `161.33.186.220`（使用者在交易所後台設定）。
3. 更新文件、記憶、登記冊裡所有「正式機＝trading-main」的地方。
4. 舊機維持凍結（停用＋`DRY_RUN_ONLY=1`）並停機，硬碟保留到 12/6 前；確定不需要退回再刪除。

## 8. 出事怎麼退回

**不論哪個階段，恢復任何一台的真倉之前，一律先做「交易所重查」**：唯讀查四支的持倉與掛單，跟 C-0 的紀錄與
該主機帳本比對；有任何不一致，兩台都保持停止（停用＋`DRY_RUN_ONLY=1`），由使用者人工裁決。

- **階段 A、B**：舊機（正式機）完全沒動。停用新主機全部服務即可；B 階段另外把開發機四支策略恢復。
- **階段 C、在 C-4 之前**：新主機還沒下過真單。
  1. 新主機跑 5.1 凍結指令，讀回 gate 零輸出。
  2. 交易所重查（上面那一條）。
  3. 通過後，舊機開關檔改回 C-0 記下的原值、讀回，逐支重新啟用，啟用後子清單讀回 `enabled`＋`active`。
- **C-4 之後**（新主機已經用真倉跑過）：
  1. **凍結兩台**：新主機比照 C-1 停止＋停用＋`DRY_RUN_ONLY=1`，讀回；舊機維持凍結。
  2. 兩台各自照第 6 段打一份唯讀快照（留存，不改）。
  3. 用第 6 段的方式把新主機的狀態**整份**反向複製到舊機（`--delete`，舊機不留切換前的舊檔），兩端完整檔案清單＋sha256
     完全相同才往下。
  4. 在舊機手動跑四支對帳，並做交易所重查；事件日誌、維運通知已送紀錄沒有重複或缺漏，才照 C-4 的方式逐支打開舊機。
  5. **任何一項對不上，兩台都保持停止，由使用者人工裁決**，不直接重啟任何一台。

## 9. 閒置回收風險

- Oracle 官方免費額度頁：Always Free 主機若連續 7 天 CPU（95 百分位）、網路、記憶體（A1）使用率都低於 20%，可能被回收；機隊用量遠低於此（A1 實測 CPU 約 2–4%、記憶體約 6%）。
- 2026-09-30 Oracle 客服回覆（引用 KB38747）：帳戶轉成隨用隨付後不會因閒置被停機；本帳戶 9/26 已轉。客服同時說免費額度 4 核心／24GB，與官方頁 2／12 矛盾，**照官方頁維持一台 2 核心／12GB**。
- 仍要防的是主機故障：A1 故障時由兩台免費小 VM 備援上線（進度頁 f-11，階段 D 之後做）。

## 10. 開發機怎麼辦

Oracle 免費額度只夠一台，給正式機用。開發機（trading-dev，GCP）12/6 後的選項，請使用者決定：

1. 續留 GCP、改付費（粗估每月約 35 美元，以 GCP 價格試算器為準）。
2. 換到別的便宜主機。
3. 不另外開開發機，只在本機開發（會少掉「先上開發機觀察」這一關，不建議）。

## 11. 使用者要做的事

- 審這份計畫，決定開發機去留（第 10 段）。
- 階段 A：部署金鑰已於 2026-09-29 由 Claude 經 GitHub API 設好（使用者授權），不需再動手。
- 階段 B、C、D 每一步開始前再確認一次。
- 階段 D 在 Binance、MEXC 後台設 IP 白名單。
