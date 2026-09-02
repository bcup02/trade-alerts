# trade-alerts 消費專案登錄與發布交接手冊

本文件是 **trade-alerts 發布的唯一交接入口**。任何介面、契約、查詢呈現或推播行為變更，都必須先更新本文件，再發布新的版本標籤。所有消費專案均應使用明確版本標籤，不得依賴 `main`。

> 版本更新的完成條件不是「套件已推送」；而是每個受影響的消費專案都已釘選、安裝、部署並驗證該版本。

## 消費專案登錄表

| 專案 | 目前整合狀態 | 版本/部署入口 | 發布後負責動作 | 最低驗證 |
|---|---|---|---|---|
| `columnbb/my-crypto-bot` | 尚待 v1 契約遷移 | 尚未建立部署相依 | 實作整合時必須在本表補上版本釘選與部署命令 | 契約測試、DRY_RUN 查詢 |
| `columnbb/MarkMinervini-cryptio-bot` | 尚待 v1 契約遷移 | 尚未建立部署相依 | 實作整合時必須在本表補上版本釘選與部署命令 | 契約測試、模擬查詢 |
| `bcup02/ed-seykota-systematic-trend-following` | 已整合投資人查詢與通知；L3 起 `src/seykota_bot/reconcile/binance_fetch.py` 消費 `trade_alerts.binance_reconcile_fetch` | `pyproject.toml` + `requirements.lock` 釘選版本；WSL `/opt/ed-seykota-systematic-trend-following/.venv`（非 editable）| 更新釘選版本、測試後重建 `/opt` venv 並重啟 `seykota-bot` + `seykota-reconcile-fetch.timer` | 已安裝版本；`audit/exchange_state.json` `schema_version=reconcile-source/v1`、`seykota-reconcile-compare` 仍 `UNKNOWN` |
| `vivoy2027game/mexc-4h-momentum-trailing-stop` | 已整合通知、唯讀投資人快照、`ledger_reconcile`（L2）；L3 起 `src/binance_fetch.py` 消費 `trade_alerts.binance_reconcile_fetch` | GitHub Actions 執行環境 + WSL `/opt/mexc-4h-momentum-trailing-stop/.venv`（`deploy/install_systemd.sh`）| 更新 `pyproject.toml` + `deploy/install_systemd.sh` + workflow 釘選後，從 `operations` 跑 `install_systemd.sh` 重新部署 | 不變更下單邏輯；`mexc-momentum-reconcile-fetch` timer 仍 `RECONCILED` exit 0、快照續發 |

## 標準發布流程

| 順序 | 維護者必做事項 | 通過條件 |
|---|---|---|
| 1 | 修改程式、Schema、文件與測試。 | 全部測試通過，且向下相容影響已記錄。 |
| 2 | 更新 `pyproject.toml` 版本，建立並推送帶註解的 Git tag，例如 `v0.8.2`。 | `main` 與 tag 均已推送。 |
| 3 | 逐一檢查本表的「已整合」專案，將相依版本從舊 tag 更新為新 tag。 | 每個受影響專案的提交均明確寫出目標版本。 |
| 4 | 依各專案部署入口部署，並執行最低驗證。 | 實際安裝版本與目標 tag 相同。 |
| 5 | 在發布紀錄中列出：套件 commit、tag、各消費專案 commit、部署時間與驗證結果。 | 交接者可不依賴口頭資訊重現狀態。 |

## Seykota 專案的特別規則

Seykota 的管理服務部署腳本會在停止 `seykota-admin.service` **之前**比較兩個版本：Seykota `pyproject.toml` 所釘選的 `trade-alerts` tag，以及目標 WSL 本機 `trade-alerts` 工作副本的 `pyproject.toml` 版本。若兩者不同，部署會明確失敗，不會以舊版覆蓋管理虛擬環境。

部署後，腳本也會從 `.admin-venv` 讀取已安裝版本；若與釘選版本不同即失敗。因此，下一位維護者只需依序更新兩個 Git 工作副本、執行部署，並確認輸出含有已驗證版本即可。

## 禁止事項

不得將任何 token、密碼、API key、帳號識別資料或 `.env` 內容寫入本文件、提交、部署輸出或發行說明。Seykota 仍必須維持 DRY_RUN；套件升級不得藉此啟用實盤、下單、轉帳或變更保護單。

## 發布紀錄模板

```text
trade-alerts：vX.Y.Z（commit <sha>）
變更摘要：<一句話說明>
受影響消費專案：<repo/branch/commit>
部署入口：<已執行的安全部署命令>
版本驗證：<實際已安裝版本>
服務/工作流程驗證：<結果>
交易安全：未啟用實盤、未下單、未修改秘密或保護單
```

## 發布紀錄

```text
trade-alerts：v0.11.0
變更摘要：apps_script/google_ledger_receiver.gs 新增 legacy 唯讀 action list_by_sheet
          （回 header + 資料列，可選 trade_ids 過濾），供各專案 google_reconcile.py
          做「本地帳本 ↔ Google 表」三方對帳；共用 Apps Script Web App 的唯讀權威源
          正式定位在本 repo 的 apps_script/（原本唯一副本在 columnbb/my-crypto-bot
          的 sheets_sync_apps_script.gs，位置屬歷史偶然）。首次加入 CI（.github/
          workflows/ci.yml：pytest + node apps_script 測試 + sticky 摘要）。
受影響消費專案：
  - columnbb/my-crypto-bot：把本地 sheets_sync_apps_script.gs 換成指向本 repo 的
    pointer；文件參照改指 apps_script/google_ledger_receiver.gs。
  - vivoy2027game/mexc-4h-momentum-trailing-stop：文件參照改指同上。
  - bcup02/ed-seykota-systematic-trend-following、columnbb/MarkMinervini-cryptio-bot：
    無 .gs 副本、無需動作。
部署入口：list_by_sheet 對現有部署的 legacy 行為為純新增、且與部署中的
          sheets_sync_apps_script.gs 逐欄等價，故 v0.11.0 本身「不需要」重新發布
          Apps Script。維護者可在方便時把 google_ledger_receiver.gs 貼進「AI自動
          程式交易紀錄」的 Apps Script 編輯器 → 管理部署作業 → 新版本（同一端點
          之後也會吃 v2），此動作需另行核准、非本次發布的完成條件。
版本驗證：消費專案的 pyproject pin 不需 bump（.gs 是手動貼上、非 import）；
          v0.11.0 只是給 .gs 一個版本座標。
服務/工作流程驗證：trade-alerts pytest + node 測試全綠；下一輪各專案
          *-reconcile-fetch timer 的 google_reconcile_status.json 仍 RECONCILED。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```

```text
trade-alerts：v0.12.0
變更摘要：新增純函式模組 src/trade_alerts/ledger_reconcile.py —— 把
          mexc-4h-momentum-trailing-stop 與 my-crypto-bot 逐字複製的對帳邏輯
          （reconcile_shared.py / reconcile_compare.py / google_reconcile.py 的
          primitives + 兩層 compare()）抽成單一權威源。匯出：
          - IO/parse helpers：read_ledger / read_json / atomic_write / parse_iso /
            utc_now_iso / to_float / to_number / env_int / env_float
          - 事件分類：is_paper_event（含 live_close_estimate_is_real 參數，
            對應 my-crypto 的 LIVE-估計平倉 carve-out）/ recorded_order_ids /
            unsettled_pending_markers
          - 第 1 層 exchange_ledger_compare()（本地帳本 ↔ 交易所，回
            ledger_status.json）
          - 第 2 層 fold_ledger_trades() + sheet_ledger_compare()（本地帳本 ↔
            Google 表，回 google_reconcile_status.json）+ fetch_sheet_rows()
          各專案差異以參數注入：is_paper / norm_symbol（norm_symbol_plain vs
          norm_symbol_ccxt）/ open_event_types / include_pending_markers。
          純新增，不動任何既有 trade-alerts 模組或行為。順帶修正
          src/trade_alerts/__init__.py 陳舊的 __version__ = "0.10.0"（pyproject
          當時已是 0.11.0）。新增 tests/test_ledger_reconcile.py（33 測試）。
受影響消費專案：
  - vivoy2027game/mexc-4h-momentum-trailing-stop：reconcile_shared.py /
    reconcile_compare.py / google_reconcile.py 改成薄 adapter，import 本模組；
    pin bump 至 v0.12.0（pyproject + deploy/install_systemd.sh）。
  - columnbb/my-crypto-bot：reconcile_compare.py / google_reconcile.py 同上；
    pin bump 至 v0.12.0（deploy/install_systemd.sh + .github/workflows/ci.yml）。
  - bcup02/ed-seykota-systematic-trend-following：不在 L2 範圍（無本地帳本、
    verdict 恆 UNKNOWN、未依賴 trade-alerts），保留自有 reconcile/compare.py。
  - columnbb/MarkMinervini-cryptio-bot：無對帳程式、無需動作。
部署入口：本次為 Python 套件純新增，不影響現有部署的行為。消費專案各自 bump
          pin 後走自己的 governance PR → Perplexity → merge-pr.sh → 從 operations
          跑 install_systemd.sh 重新部署，驗證 *-reconcile-fetch timer 仍綠。
版本驗證：pip show trade-alerts == 0.12.0；trade_alerts.__version__ == "0.12.0"。
服務/工作流程驗證：trade-alerts pytest（87）+ node 測試全綠。消費專案 adapter
          PR 合併部署後，三軸 reconcile 狀態不變（momentum/my-crypto 的
          ledger_status.json 與 google_reconcile_status.json 仍 RECONCILED）。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```

```text
trade-alerts：v0.13.0
變更摘要：新增純函式模組 src/trade_alerts/binance_reconcile_fetch.py —— 把
          ed-seykota 與 mexc-4h-momentum-trailing-stop 各自一份、幾乎逐位元相同的
          唯讀 Binance USDⓈ-M reconcile-source fetcher（balance / positionRisk /
          userTrades / openOrders / openAlgoOrders → reconcile-source/v1 文件）
          抽成單一權威源。任務 3 L3。
          - 不 import binance_trading_toolkit：client（toolkit BinanceFuturesClient
            或同介面物件）由呼叫端注入，測試用 fake。憑證解析 / mainnet 判定 /
            EXCHANGE 分流留在各 repo 的憑證層。
          - BinanceReconcileParams dataclass 注入 per-repo 差異：query_symbols
            （Binance 原生形式，userTrades 逐 symbol）/ scope_symbol（
            position_information·open_orders·open_algo_orders 的範圍；momentum=None
            全部、seykota=其 symbol）/ doc_symbol / to_ledger_symbol（identity vs
            momentum_ledger_symbol 的 GPSUSDT→GPS_USDT）/ lookback_hours。
          - fetch() 一律輸出 symbols_queried + fills_possibly_truncated（seykota
            文件多這兩欄＝無害超集，exchange_ledger_compare 忽略未知鍵）。
          - _order_rows 帶 T1-6 PR #41 的 algo 欄位修正（orderType / createTime）
            —— seykota 順帶受惠。
          - run() 重用 ledger_reconcile.atomic_write，永不 raise。
          純新增，不動任何既有模組或行為。新增 tests/test_binance_reconcile_fetch.py。
受影響消費專案：
  - bcup02/ed-seykota-systematic-trend-following：src/seykota_bot/reconcile/
    binance_fetch.py 縮成薄 adapter（單 symbol、state key = mode、
    settings.credentials_for）；pyproject.toml + requirements.lock 新增
    trade-alerts@v0.13.0 相依（此前完全未依賴 trade-alerts）。
  - vivoy2027game/mexc-4h-momentum-trailing-stop：src/binance_fetch.py 縮成薄
    adapter（多 symbol、state key = execution_mode、binance_credentials）；同時
    還原 src/reconcile_mexc_fetch.py（T1-5 刪除）+ 新增 src/reconcile_fetch.py
    dispatcher（依 EXCHANGE 選 Binance / MEXC fetcher），修好切回 EXCHANGE=mexc
    時對帳 fetcher 仍打 Binance 的缺口；pin bump 至 v0.13.0（pyproject +
    deploy/install_systemd.sh + .github/workflows/*.yml）。
  - columnbb/my-crypto-bot：不動（其 reconcile_mexc_fetch.py 是 ccxt 單 symbol、
    單一消費者、不同 client stack，不強抽）。
  - columnbb/MarkMinervini-cryptio-bot：無對帳程式、無需動作。
部署入口：Python 套件純新增。消費專案各自 bump pin 後走 governance PR →
          Perplexity → 合併 → 重新部署，驗證 *-reconcile-fetch timer 仍綠。
版本驗證：pip show trade-alerts == 0.13.0；trade_alerts.__version__ == "0.13.0"。
服務/工作流程驗證：trade-alerts pytest（110）+ node 測試全綠。消費專案 adapter
          PR 合併部署後，seykota reconcile 仍 UNKNOWN（無帳本，預期）、momentum
          ledger_status.json 與 google_reconcile_status.json 仍 RECONCILED。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```
