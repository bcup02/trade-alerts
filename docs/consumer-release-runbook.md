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

```text
trade-alerts：v0.13.1
變更摘要：binance_reconcile_fetch — `BinanceReconcileParams.query_symbols` 除了
          固定序列，現在也接受 callable(position_rows) -> Sequence[str]。momentum
          的對帳需要「fills 視窗 = 目前開倉部位的 symbol ∪ 靜態 RECONCILE_SYMBOLS
          env」，而部位要 fetch 完才知道；callable 在 positions section 之後被呼叫、
          收到正規化（ledger 形式）的部位列。seykota 仍傳固定 `[symbol]`，行為不變。
          positions section 失敗時 callable 收到 []（靜態 env 仍納入）。
          純向後相容擴充（list 照舊）。+2 測試（112）。
受影響消費專案：
  - vivoy2027game/mexc-4h-momentum-trailing-stop：PR-3 的 adapter 用 callable 形式；
    pin 直接鎖 v0.13.1。
  - bcup02/ed-seykota-systematic-trend-following：無需動作（PR-2 已鎖 v0.13.0、用
    固定序列；可在下次順帶把 pin 提到 v0.13.1，非必要）。
部署入口：Python 套件純擴充。
版本驗證：pip show trade-alerts == 0.13.1；trade_alerts.__version__ == "0.13.1"。
服務/工作流程驗證：trade-alerts pytest（112）+ node 測試全綠。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```

```text
trade-alerts：v0.13.2
變更摘要：deliver_projection_v2 — receiver 的 `ok:false` 錯誤不再一律當終端
          `REJECTED`。只有「payload 結構本身壞」的少數錯誤（provenance_invalid /
          open_projection_invalid / close_projection_invalid）才是 REJECTED；
          其餘（unauthorized / signature_invalid / source_not_allowed /
          unsupported_action / request_not_fresh / sheet_not_found / malformed…）
          都是「設定／部署尚未就緒」的問題，同一筆意圖修好後可成功，故改回
          可重試的 `TRANSPORT_FAILED`，durable outbox 保留該意圖而非燒掉。
          動機：momentum 首次啟用 v2 遞送時，共用 Apps Script Web App 是舊版
          （v2 payload 被路由到 legacy secret 檢查 → unauthorized），26 筆積壓
          意圖被 drain 一次全部標成終端 REJECTED、無法再送。+1 測試（113）。
受影響消費專案：
  - vivoy2027game/mexc-4h-momentum-trailing-stop：pin bump 至 v0.13.2（pyproject
    + deploy/install_systemd.sh）；已被燒掉的 26 筆意圖由 momentum 端的
    reset 工具（scripts/reset_google_projection_outbox.py）清掉終端 dispatch 記錄
    後重新變 outstanding。
  - bcup02/ed-seykota-systematic-trend-following：Phase C 才會用到 v2 遞送，
    屆時直接鎖 v0.13.2。
部署入口：Python 套件行為修正（狀態分類）。
版本驗證：pip show trade-alerts == 0.13.2；trade_alerts.__version__ == "0.13.2"。
服務/工作流程驗證：trade-alerts pytest（113）+ node 測試全綠。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```

```text
trade-alerts：v0.13.3
變更摘要：apps_script/google_ledger_receiver.gs（+ 同步的參考副本
          google_ledger_receiver_v2.gs）—— v2 投影寫入 sheet 時，entry_time /
          exit_time 從 ledger 帶來的 UTC ISO-8601（opened_at / closed_at）改成
          轉台北時區文字 "yyyy-MM-dd H:mm:ss"（Asia/Taipei，無 DST），與 v2 之前
          各策略寫的舊列格式一致。新 helper formatSheetTime()（空值 / 已是台北
          文字 / 不可解析 → 原樣通過，不拋）；needsTextFormat() 取代 4 處內嵌的
          16+ 位數字檢查，讓台北 datetime 文字也維持左對齊純文字、不被 Sheets
          自動解析成日期值。sheetValue() 對 entry_time / exit_time 走新分支。
          payload_digest 不受影響（轉換在 receiver 側、驗章之後）；
          google_reconcile 不比對時間欄，對帳判定不變。+3 node 斷言。
          動機：v2 drain 補進表的 ~25 筆列時間欄是 UTC ISO（2026-08-29T15:57:11Z），
          與舊列（2026-08-26 0:00:49）格式不符。
受影響消費專案：
  - 全部：不需 bump pin（.gs 是手動貼上、非 import；v0.13.3 只是 .gs 的版本座標）。
  - 已寫錯的 ~25 筆既有列由 momentum 端一支改寫工具（讀 list_by_sheet → 逐列
    update_by_trade_id 送台北文字）修掉；那條路徑也會經過 needsTextFormat 的
    @ 文字格式化。
部署入口：需維護者手動把 google_ledger_receiver.gs 貼進「AI自動程式交易紀錄」的
          Apps Script 編輯器 → 管理部署作業 → 新版本（同一 Web App URL 不變、
          影響所有分頁、Script Properties 不動）。此動作需另行核准。
版本驗證：pip show trade-alerts == 0.13.3；trade_alerts.__version__ == "0.13.3"。
          重新發布後：下一筆 v2 投影的 entry_time / exit_time 在表上為台北文字、
          左對齊。
服務/工作流程驗證：trade-alerts pytest（113）+ node 測試全綠。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```

```text
trade-alerts：v0.13.4
變更摘要：apps_script/google_ledger_receiver.gs —— 修 v0.13.3 的遺漏。legacy
          寫入路徑 handleLegacyUpdateByTradeId / handleLegacyUpdateByKey 的
          cell.setNumberFormat('@') 之前在 cell.setValue() 之後才呼叫，順序反了：
          Sheets 會先把 datetime 形狀的字串解析成 Date serial（若該 cell 原本
          帶「不顯示秒」的日期數字格式，秒數就在顯示層被丟掉），setNumberFormat('@')
          再把「已被重新格式化的顯示字串」凍成文字 —— 結果 "2026-08-20 2:25:00"
          變成 "2026-08-20 2:25"。改成先 @ 格式、再 setValue。handleLegacyAppend
          已是先格式再 setValues（forEach 設 @ 後才 range.setValues），不需動；
          v2 writeProjection 一直是先 @ 再 setValue，不受影響。
          node 測試：sheet stub 加 callLog 記錄 setValue / setNumberFormat 呼叫
          順序，斷言 update_by_trade_id / update_by_key 對 datetime 形狀的欄位
          是「setNumberFormat 先於 setValue」。
          動機：R6 改寫工具（momentum rewrite_sheet_times_to_taipei.py）走
          update_by_trade_id 修那 ~25 筆列時，3 筆原本是 Date-value 的列（cell
          帶日期格式）被這個順序 bug 弄掉了 :00 秒。
受影響消費專案：
  - 全部：不需 bump pin（.gs 手動貼上、非 import；v0.13.4 只是版本座標）。
  - momentum：rewrite_sheet_times_to_taipei.py 同步放寬 canonical_taipei 接受
    "YYYY-MM-DD H:MM"（無秒）→ 補 :00，重跑 --apply 修那 3 筆。
部署入口：需維護者手動把 google_ledger_receiver.gs 重新貼進 Apps Script 編輯器
          → 管理部署作業 → 新版本（同 Web App URL、影響所有分頁、Script
          Properties 不動）。此動作需另行核准。
版本驗證：pip show trade-alerts == 0.13.4；trade_alerts.__version__ == "0.13.4"。
          重新發布後：update_by_trade_id 寫 datetime 字串進原本是 Date-value 的
          cell，秒數不再掉。
服務/工作流程驗證：trade-alerts pytest（113）+ node 測試全綠。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```

```text
trade-alerts：v0.14.0（commit aa859b1）
變更摘要：新模組 verified_close_backfill——把 momentum 的
          fetch_verified_close_evidence.py / append_reconciled_close.py 移植
          （非複製）成交易所無關的共用核心：從本地 trade_open + 標準化
          exchange fills（binance_reconcile_fetch.fill_rows 已用的
          reconcile-source/v1 形狀）組出 schema-1.0 evidence dict，再透過
          注入的 ledger_append callable 寫入證據型修復事件（
          reconciliation_evidence_recorded / fill / trade_close /
          position_reconciled_closed）——不自建交易所 client，也不自建任何
          專案自己的 TradeLedger，任何吐得出標準化 fill 形狀的交易所轉接器
          都能餵它，任何專案自己的 ledger 類別都能吃它。同時修正移植時發現的
          舊 bug：method 欄位原本寫死
          "read_only_mexc_history_orders_and_deals"，現在改成呼叫端傳入的
          參數，讓沒有這欄位的舊證據（用 momentum 真實 MUBARAK evidence
          fixture 驗證過）能安全退化成中性標籤。binance_reconcile_fetch 的
          position_rows / fill_rows 改為公開（原 _position_rows /
          _fill_rows 單純改名，邏輯不變），讓專案的 verified-close CLI 可以
          直接查窄範圍的 symbol+window，不必走較重的完整 fetch()。
受影響消費專案：本次 PR 只新增共用核心，未改動任何消費專案；momentum 既有
          兩支工具留待後續 PR 改用。
部署入口：無（純函式庫新增，未觸發任何部署）。
版本驗證：pip show trade-alerts == 0.14.0；trade_alerts.__version__ ==
          "0.14.0"。
服務/工作流程驗證：trade-alerts pytest（127）全綠。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```

```text
trade-alerts：v0.14.1（commit f69002a）
變更摘要：build_evidence() 原本把每筆 deal 的 exchange_side 寫死成
          "SELL"，只在純多單消費者（momentum）身上剛好是對的。在幫 seykota
          的轉接器估工時發現：seykota 雙向都做（bot.py 用 "SELL" if
          p.side == "long" else "BUY"），空單真正的平倉 fill 是 BUY 方向，
          寫死 SELL 會永久標錯。改成從每筆標準化 fill 自己的 side 欄位
          （轉大寫）推導 exchange_side，只有呼叫端的 fills 完全沒帶 side
          時才退回 "SELL"（向後相容——momentum 既有的 _precise_fill 本來
          就有填 side，輸出逐位元組不變，不需要改動）。
受影響消費專案：momentum 輸出不變，不需 bump pin 就相容；seykota 之後接入
          時會需要這個修正（雙向交易）。
部署入口：無（純函式庫修正，未觸發任何部署）。
版本驗證：pip show trade-alerts == 0.14.1；trade_alerts.__version__ ==
          "0.14.1"。
服務/工作流程驗證：trade-alerts pytest（129，+2 針對雙向 side 的斷言）全綠。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```

```text
trade-alerts：v0.14.2（commit 4c65ce1）
變更摘要：build_repair_events() 原本無條件用 gross_pnl = (exit_price -
          entry_price) * exit_volume * contract_size——對多單（漲才賺）是對
          的，對空單（跌才賺）方向完全反了。同樣在幫 seykota 轉接器估工時
          發現（seykota 雙向交易，momentum 目前只做多）。方向改成從平倉
          fills 自己的 exchange_side（v0.14.1 才有）推導：只有明確是
          "BUY"（平掉一個空單）才翻轉正負號；其餘所有值——包含 "SELL"、
          任何無法辨識的值、以及 v0.14.0 之前帶著 MEXC 數字 side code 的舊
          證據（真實 MUBARAK fixture 的 exchange_side=3）——一律維持原本
          的多單公式。刻意設計成「在明確訊號下才選擇啟用新的空單算法」，
          不是「在模糊訊號下退出行之有年的預設」，所以任何早於雙向支援的
          證據格式都不會被誤讀。3 個新測試：下跌時空單平倉會賺錢、上漲時
          多單平倉仍照舊賺錢（方向不變）、真實舊版 fixture 的數字 side code
          仍解析成多單公式。
受影響消費專案：momentum 輸出不變，不需 bump pin 就相容；seykota 之後接入
          時會需要這個修正（雙向交易）。
部署入口：無（純函式庫修正，未觸發任何部署）。
版本驗證：pip show trade-alerts == 0.14.2；trade_alerts.__version__ ==
          "0.14.2"。
服務/工作流程驗證：trade-alerts pytest（132，+3 針對空單方向的斷言）全綠。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```

```text
trade-alerts：v0.15.0（Phase 4a）
變更摘要：新增三個模組，全部是資料結構與不變式，沒有任何執行期副作用（不讀秘密、
          不開連線、不 import 交易所 client）。
          1. safe_halt_model —— 全機隊共用的一份 latch 形狀與一套 fingerprint
          演算法。Phase 4 之前 momentum 用單一 dict、btc 用 4 個扁平欄位、
          seykota 把 SAFE_HALT 塞在跟 FLAT/LONG 共用的 state.status 字串裡、
          my-crypto 沒有 latch；三支 resume 工具算出三種 fingerprint，而且只有
          momentum 的解除對帳本冪等。這支統一 build_safe_halt()／
          safe_halt_fingerprint()／resume_preview()／check_confirmation()／
          safe_halt_cleared_fields()／assert_not_already_cleared()。兩個刻意
          偏離 Phase 3 初版設計的決定：fingerprint 不存進 state（動態算，
          消掉「存下來的副本跟 latch 走鐘」這個形狀），以及 evidence（穩定
          事實、fingerprint 的唯一輸入）與 details（每輪會變的診斷資訊）在
          寫入端就分開——混在一起會讓 confirmation token 每輪跳動，latch 變成
          永遠無法解除。
          2. fleet_event_log —— append-only JSONL 事件日誌，逐專案一個檔，
          放策略的 audit/。形狀與鎖定照 projection_outbox（flock 獨佔附加 +
          fsync + 共享鎖讀取）。這個模組不通知任何人、也不決定風險等級；
          measurements 欄位收「只是指標」的數值（reconciliation_delta 每筆
          都寫、什麼都不升級）。另含 catalog_code()／risk_tier_for() 讓呼叫端
          把不帶前綴的條件名 join 回目錄。
          3. error_request_queue —— 跨過門檻的錯誤開一張請求，帶錯誤碼、
          風險等級、證據，開著直到 outcome 關掉。開請求仍然不通知。R0 條件
          永遠不能開請求（寫在函式裡，不是留給呼叫端自律）；去重鍵是
          (project, code, evidence)，同一條件連續成立多輪只有一張請求；
          已關閉的請求拒絕再關一次。
          兩份新 schema：schemas/fleet-event-log-v1.schema.json、
          schemas/error-request-queue-v1.schema.json。
受影響消費專案：無立即影響（純新增，既有公開 API 逐一未變）。Phase 4c 的
          seykota／btc／momentum latch 統一會 bump pin 到這個版本並改用
          safe_halt_model；在那之前三支照舊各自的實作運作。
部署入口：無（純函式庫，未觸發任何部署）。
版本驗證：pyproject.toml version == 0.15.0；trade_alerts.__version__ ==
          "0.15.0"。
服務/工作流程驗證：trade-alerts pytest 160 全綠（126 → 160，+34：11 條
          safe_halt_model、11 條 fleet_event_log、12 條 error_request_queue）。
          其中三條是會讀已發布目錄的硬性不變式：前綴表不得與目錄的 code 前綴
          drift、目錄不得規定沒有實作的 resume 路徑、目錄裡每一筆 R0 條件
          逐筆試開請求都必須被拒。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```

```text
trade-alerts：v0.16.0（Phase 5a）
變更摘要：Phase 5「修復 bot 影子模式」的共用地基，全部是純函式庫改動，無任何
          執行期副作用。
          1. AlertDispatcher._send_text／publish／publish_contract／test 改回
          傳 bool（是否至少一個 channel 送達），取代原本的 None。單一 channel
          失敗仍只記 log、不中斷其他 channel——只是把「有沒有送達」的結果讓
          呼叫端看得到。既有呼叫端（四支策略的 alerts.publish(...)）忽略回傳
          值照樣能跑，向下相容。這是 Phase 7「計時器只在通知確認送達後才開始
          倒數」的地基，現在先修不用等到 Phase 7。
          2. verified_close_backfill 新增兩個純函式：
             - detect_repair_candidates(ledger_status, ledger_events)——把
             reconcile_compare.py 的 DIVERGED 判定裡 evidence.position_diffs
             的 symbol 級數量差，換算成候選 trade_id（該 symbol 唯一還沒
             trade_close 的 trade_open）。symbol 沒有落在 position_diffs、
             已經有 close、或同一 symbol 有一筆以上未結案 trade_open（有歧義）
             都回傳空——只在無歧義時才給答案，不猜。這正是
             reconcile_apply.py 目前明確拒絕、留給「之後的 PR」處理的那個
             case（見其 module docstring）。
             - render_repair_proposal_text(evidence, repair_events, project)——
             把 build_repair_events() 算出的完整修復內容，組成人看得懂的 LINE
             通知文字（trade_id、symbol、數量、進出場價、手續費、本地淨損益
             vs 交易所毛損益、差額、證據來源、平倉時間），對應
             fleet-error-catalog.md §2 的 R1 PROPOSE 語意：算出方案才通知，
             附上提案。純字串組裝，不呼叫任何 channel。
受影響消費專案：無立即影響（純新增 + 回傳型別放寬，既有呼叫端不用改）。
          Phase 5b／5c 的 momentum／seykota 影子模式 bot 會 bump pin 到這個
          版本並呼叫這兩個新函式；在那之前四支策略照舊運作。
部署入口：無（純函式庫，未觸發任何部署）。
版本驗證：pyproject.toml version == 0.16.0；trade_alerts.__version__ ==
          "0.16.0"。
服務/工作流程驗證：trade-alerts pytest 169 全綠（161 → 169，+8：core.py 2 條
          新增回傳值斷言（全部 channel 失敗 / 無 channel 都回 False，另 3 條
          既有測試補上 bool 斷言）+ detect_repair_candidates 5 條 +
          render_repair_proposal_text 1 條）。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```

```text
trade-alerts：v0.17.0（Phase 6a）
變更摘要：Phase 6「低風險自動執行」的共用核心，全部是純函式庫改動，無任何
          執行期副作用；本版本自己不會讓任何東西自動寫帳本，只是把「能不能
          自動寫」這個判斷跟「要寫就整批一次寫」的機制準備好。
          1. verified_close_backfill.assess_auto_repair(evidence,
          ledger_events, *, candidate_count, still_open_checked,
          max_exchange_pnl_residual)——「完全無歧義」的唯一判定點，回傳
          {"eligible", "blockers", "checks"}。任何無法判斷的輸入都是 blocker
          而不是例外，因為每個 blocker 的意思都一樣：退回提案、不要自己動手。
          七條檢查：本輪候選數必須恰好 1、交易所必須已確認無部位、平倉成交
          必須全部是多單 SELL 方向、每筆成交時間不得早於 trade_open、證據必須
          帶 per-deal 時間戳、帳本不得留有同 incident_id 的痕跡、本地毛損益與
          交易所回報的已實現損益差額不得超過容忍值（預設 0.01 USDT）。
          **容忍值比的不是 reconciliation_delta 本身**：Phase 4e 實測該值恆
          等於 -(entry_fee + exit_fee)，一般約 -0.5 USDT，直接用小容忍值去比
          會擋掉每一筆真實修復；真正該接近零的是手續費解釋不掉的那部分。
          2. verified_close_backfill.incident_traces()——比既有 _existing_repair
          更廣：後者只看 trade_close／position_reconciled_closed 兩個終端事件，
          但一批寫到一半停掉會只留下 reconciliation_evidence_recorded 跟 fill，
          對終端檢查完全隱形。有任何痕跡就交給人判斷，絕不自己補完後半段。
          3. 新模組 atomic_ledger_append：append_lines_atomically(path, lines)
          把整批事件在 exclusive_log_lock 內一次 write + flush + fsync，寫完
          re-read 驗證每一行都在。行內容由呼叫端自己的 TradeLedger 產生
          （staging 寫到暫存檔後用 stage_lines 讀回），所以帳本格式仍然由各專案
          自己擁有、不會 drift。刻意不做失敗回捲：這裡的鎖是 sibling .lock，
          而策略 bot 自己的 TradeLedger.append 完全不上鎖，truncate 回捲可能
          砍掉 bot 併發寫進去的事件。
          4. build_evidence 的每筆 deal 新增 time_ms（additive，舊證據檔沒有
          這個欄位就會被 assess_auto_repair 當成「視窗無法驗證」而擋下自動修復，
          退回提案模式）。
          5. append_repair_from_evidence()——吃記憶體裡的 evidence dict，既有
          append_repair() 改為 load_evidence 後委派，簽章與行為完全不變。
          6. 錯誤目錄 risk_tiers 新增 audit_notice 欄位（只有 R2 為 true）+
          §2.1 明文定義「事後稽核通知」與「決策請求通知」是兩件事，前者只告知
          已完成的動作、不問任何問題。既有那條治理不變式
          test_mechanical_verdicts_never_reach_a_notifying_tier 一個字都沒改
          （它只讀 notifies，R2 仍是 false），另加兩條新不變式守住兩者不得同時
          為真、且只有會自動執行的等級才可能有事後稽核。
受影響消費專案：無立即影響（純新增 + 一個 additive 證據欄位）。Phase 6b 的
          momentum 自動修復會 bump pin 到這個版本；seykota／my-crypto／btc
          照舊運作，seykota 明確維持影子模式不變。
部署入口：無（純函式庫，未觸發任何部署）。
版本驗證：pyproject.toml version == 0.17.0；trade_alerts.__version__ ==
          "0.17.0"。
服務/工作流程驗證：trade-alerts pytest 205 全綠（169 → 205，+36：
          assess_auto_repair 21 條（每個 blocker 各一條，避免某條檢查默默失效
          時沒有任何測試會紅；含殘差容忍值邊界三點與大額高價部位殘差恆為零）、
          incident_traces 1 條、append_repair_from_evidence 2 條、
          atomic_ledger_append 10 條、錯誤目錄新不變式 2 條）。
          其中 test_a_torn_trailing_line_from_an_earlier_crash_reads_as_nothing
          在開發過程中抓到一個真實缺陷：帳本最後一行若因先前崩潰而斷尾（無換行
          結尾），直接 append 會把新批次第一筆黏進斷行、同時毀掉兩筆；已修成
          先補一個換行，讓斷尾自成一行被 read_ledger 跳過。
          Perplexity 首審 BLOCK（incident_id 為空字串時痕跡檢查被靜默跳過）→
          修正為「缺 trade_id／incident_id 本身即 blocker」，並加一條更廣的
          檢查：同一 trade_id 下帶任何其他 reconciliation 紀錄的事件也擋下
          （不依賴 incident_id 相符）。修正前以舊程式碼跑新測試確認 4 條紅。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```

```text
trade-alerts：v0.17.1（Phase 6b 配套）
變更摘要：1. 錯誤目錄補登 momentum 修復 bot 的三條條件（sources 指向
          AI-for-column/mexc-4h-momentum-trailing-stop PR #88 的
          scripts/repair_bot.py）：
          - MOM.VERIFIED_CLOSE_AUTO_REPAIRED — MECHANICAL／R2／P6：開關開啟
            且判準全部成立才自動寫帳本，事後稽核通知。
          - MOM.VERIFIED_CLOSE_PROPOSED — JUDGEMENT／R1／P5：補登 Phase 5
            影子模式既有行為（當時只在程式碼註解宣告 R1）。
          - MOM.VERIFIED_CLOSE_REPAIR_BLOCKED — JUDGEMENT／R4／P6：帳本已有修復
            痕跡或整批寫入失敗 → 停手、critical 一次；「重複提醒」節奏屬 Phase 7。
          目錄 30 → 33 條，docs/fleet-error-catalog.md §3 計數與 §3.2 表同步。
          Perplexity 首審 BLOCK：AUTO_REPAIRED 的 rationale 原寫「任何一條判準
          不成立都退回 PROPOSED」，漏掉「帳本已有修復痕跡 → REPAIR_BLOCKED（R4，
          critical）」這條分流。已改寫成完整列出三條退路，並補上「交易所仍有部位
          時在抓證據階段就中止、不通知」。
          既有不變式一條未改，三條新條目全部通過。
          2. assess_auto_repair 內兩處 trade_id 比對補上 str()（找 trade_open
          與同交易其他修復痕跡），與同段其他檢查一致。PR #21 複審的遺留非阻擋
          觀察；現行 trade_id 全為字串，不可觸發。
受影響消費專案：momentum PR #88 pin 由 v0.17.0 改為 v0.17.1。其餘不受影響。
部署入口：無（純函式庫 + 目錄資料）。
版本驗證：pyproject.toml version == 0.17.1；trade_alerts.__version__ ==
          "0.17.1"。
服務/工作流程驗證：trade-alerts pytest 206 全綠（205 → 206，+1：
          test_assess_matches_trade_ids_across_str_and_int，以 v0.17.0 程式碼
          執行確認會紅）。錯誤目錄不變式（含雙向治理不變式、audit_notice 兩條）
          對 33 條全數通過。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```

```text
trade-alerts：v0.18.0（Phase 7b）
變更摘要：修復 bot 的通知目前在兩台主機都被靜默丟棄（策略 env 維持
          ALERTS_ENABLED=false）。本版提供「策略整理、ops-notify 代送」所需
          的共用部分：
          1. 錯誤目錄改為 package data：catalog/fleet-error-catalog-v1.json
             移到 src/trade_alerts/catalog/（pyproject package-data），
             load_error_catalog() 不帶路徑時讀套件內那份。策略主機是 pip 從
             git tag 安裝（非 editable），先前根本讀不到這份檔案。已用乾淨
             venv 非 editable 安裝驗證 site-packages 內可讀到 33 條。
          2. 目錄 entry 新增可選欄位 operator_message {what, direction,
             steps[]}（白話：發生什麼事／解決方向／處理步驟）；先寫 momentum
             修復 bot 三條（MOM.VERIFIED_CLOSE_PROPOSED／AUTO_REPAIRED／
             REPAIR_BLOCKED）。新不變式三條：三段皆非空、R0 不得有、momentum
             三條必須有；另一條確認 load_error_catalog() 讀到的就是測試讀的檔。
          3. 新模組 ops_export：build_ops_export(fleet_event_log,
             request_queue, *, project, catalog=None, window_days=7) 產生
             fleet-ops-export/v1（notices：近 7 天 R1–R4 事件，含組好的完整
             訊息 text；open_requests：未結案請求附白話三段，
             handling_started_at 本版恆 null、7e 才寫）；write_ops_export()
             原子替換、0644。新 schema schemas/fleet-ops-export-v1.schema.json。
          既有 API 簽章不變；load_error_catalog(path) 仍可傳路徑。
受影響消費專案：momentum（Phase 7b 第二個 PR）pin 改為 v0.18.0 並寫
          audit/ops_export.json；ops-notify 讀該檔（不 import 本套件的新 API，
          不需要跟著 bump）。seykota／my-crypto／btc 不受影響。
部署入口：無（純函式庫 + 目錄資料）。
版本驗證：pyproject.toml version == 0.18.0；trade_alerts.__version__ ==
          "0.18.0"。
服務/工作流程驗證：trade-alerts pytest 229 全綠（206 → 229，+23：
          ops_export 19 條、錯誤目錄不變式 4 條）。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```

```text
trade-alerts：v0.18.1（Phase 7b 配套，純目錄資料）
變更摘要：1. 錯誤目錄三條 MOM.VERIFIED_CLOSE_* 的 sources 行號跟上 momentum
             PR #90（scripts/repair_bot.py：PROPOSED :123→:128、REPAIR_BLOCKED
             :143→:153、AUTO_REPAIRED :217→:228；以 momentum development
             44524e0 grep 驗證）。
          2. 補 v0.17.1 歸檔留下的兩條非阻擋觀察（MOM.VERIFIED_CLOSE_AUTO_REPAIRED
             rationale）：「其餘判準不成立」清單加上「缺 trade_id／incident_id
             等」，不再讀起來像窮舉；抓證據階段靜默中止的原因補上「證據結構不足
             以算出修復事件（build_repair_events 拋 VerifiedCloseError）」。
          程式碼零變更。
受影響消費專案：無執行期影響；momentum 維持 v0.18.0 即可（sources／rationale
          不參與通知文字）。
部署入口：無。
版本驗證：pyproject.toml version == 0.18.1；trade_alerts.__version__ ==
          "0.18.1"。
服務/工作流程驗證：trade-alerts pytest 229 全綠（無新增測試）。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```

```text
trade-alerts：v0.19.0（風險分級 v2，W1a）
變更摘要：使用者 2026-09-18 拍板把錯誤分級由五級改四級（計畫 W1）。
          1. 錯誤目錄升 fleet-error-catalog/v2（檔名 -v2.json，v1 移除）：
             R0 只記錄／R1 自動、不通知（舊 R2）／R2 自動嘗試、連續
             escalate_after（3）次失敗才升格通知（舊 R1＋舊 R3）／R3 必須
             人工（舊 R4）。v1 的「提案」「逾時自動執行＋Telegram 提早核准」
             「事後稽核通知 audit_notice」全部取消。33 條逐條重新分級（R0 9／
             R1 2／R2 11／R3 11），被改變語意的條目同步改寫 auto_action／
             human_action／rationale（含 seykota 孤兒停損單自動取消的兩道安全
             條件）。新增 retired_codes：MOM.VERIFIED_CLOSE_PROPOSED（呼叫點由
             共用修復執行器取代時退役）、SEY.VERIFIED_CLOSE_PROPOSED（seykota
             影子 bot 一直在發、v1 卻從未登記）。
          2. 33 條全部補 operator_message（v1 只有 3 條），R2／R3 另帶
             ai_prompt（給 AI 的根因追查指令）。
          3. 程式：RISK_TIERS 改四級；REQUESTABLE_TIERS 只剩 R2／R3；
             ops_export 只匯出 R3 與 details.escalated 為真的 R2（needs_human），
             訊息附 ai_prompt＋本次事件的錯誤碼／事件編號／evidence；
             fleet-ops-export 升 v2（open_requests 多 ai_prompt）。
             事件日誌／請求佇列兩份 schema 的等級列舉同步。
          兩台主機的 fleet_event_log／error_requests 目前都不存在（已實測），
          改變等級語意不需要搬資料。
受影響消費專案：momentum（目前 v0.18.0，寫的是 v1 等級；W3 改用共用執行器
          時一併升級）、ops-notify（讀 fleet-ops-export/v1；W5 升級）。
          兩者在升級前都不會讀到 v2 的任何東西。seykota／my-crypto／btc 不受影響。
部署入口：無（純函式庫 + 目錄資料）。
版本驗證：pyproject.toml version == 0.19.0；trade_alerts.__version__ ==
          "0.19.0"。
服務/工作流程驗證：trade-alerts pytest 全綠（見 PR）。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```

```text
trade-alerts：v0.20.0（風險分級 v2，W1b：機隊一致性登記冊）
變更摘要：1. 新 src/trade_alerts/catalog/fleet-rollout-registry.json（隨套件發佈）
             ＋ schemas/fleet-rollout-registry-v1.schema.json：12 項機隊功能 ×
             四支策略，以及錯誤目錄 33 條各自的「行為」與「寫進事件日誌」
             在所屬策略的狀態——done（附證據）／pending（附預定 phase＋理由）
             ／n/a（附理由）。種子內容 2026-09-18 對四個 repo 逐項實查填入。
             done＝真倉已經在跑：sources 記錄每支策略的 repo、operations
             分支與 commit，所有 done 證據都是該 commit 的「檔案:行號」。
             （首審 BLOCK：momentum 有 6 格把只在 development 的 Phase 6b
             repair_bot.py 當成 done 或當成現況，已改為 pending 並寫明。）
          2. 新模組 trade_alerts.rollout_registry：load_rollout_registry()、
             registry_problems()（規則的可執行版：四支列滿、pending 有登記過的
             phase 與理由、done 有證據、目錄與登記冊逐條對得上、退役碼只能是
             pending）、project_rows()（給策略 repo 自我檢查）。
          3. 新 scripts/render_guides.py：由錯誤目錄＋登記冊產生
             docs/guides/fleet-risk-register.html（改為 v2 四級、33 條、各策略
             實作狀態），由登記冊產生新頁 docs/guides/fleet-rollout-register.html。
             兩頁不可手改，CI 比對重新產生的結果。
          4. 新 tests/test_rollout_registry.py（39 條）：打包登記冊一致、每條規則
             各有一個反例（含 sources）、每個 done 都引用檔案、兩頁＝重新產生、
             頁面不以 innerHTML 注入資料。
          5. 新 scripts/verify_registry_evidence.py：對本機四個 repo 在 sources
             commit 逐條檢查證據（跨 repo，手動執行、不在 CI）。
          兩頁已用無頭 Chromium 在桌機／400px 手機 × 淺色／深色實測：無主控台
          錯誤、無橫向捲動、篩選按鈕行為正確。
受影響消費專案：無執行期影響（登記冊只有測試與頁面產生器讀取）。
          策略 repo 之後可升級並以 project_rows() 加自我檢查（計畫 W3/W4）。
部署入口：無（純函式庫 + 資料 + 靜態頁）。
版本驗證：pyproject.toml version == 0.20.0；trade_alerts.__version__ ==
          "0.20.0"。
服務/工作流程驗證：trade-alerts pytest 全綠（見 PR）。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```

```text
trade-alerts：v0.21.0（風險分級 v2，W2：共用修復執行器）
變更摘要：1. 新模組 trade_alerts.repair_runner：run_repair_round(adapter, paths) 是全機隊唯一的
             漏記平倉自動修復，策略只提供 RepairAdapter（fetch_evidence／staging_ledger／
             queue_projection）。能對應 → R1 寫入、不通知；交易所仍有部位（PositionStillOpen）
             → 不算失敗；查交易所失敗或結構對不上 → R2 記一次失敗，同一 trade_id 連續 3 次
             才開請求並標 escalated（ops_export 通知一次），之後靜默重試、成功則 RESOLVED_AUTO；
             帳本已有修復痕跡或整批寫入失敗 → R3 停手、永不重試；帳本出現該筆 trade_close
             → 請求 WITHDRAWN。一輪最多寫一筆，多筆依序逐輪補。<PROJECT>_REPAIR_PAUSED
             統一煞車（停手時仍刷新 ops_export）。執行器不直接推播。
          2. verified_close_backfill：
             - build_repair_events：本地毛損益與交易所已實現損益差 > 0.01 時以交易所為準，
               reconciliation 記 pnl_source=exchange_realized／local_gross_pnl／
               exchange_pnl_residual；差額在容忍內時產出與 v0.20.0 逐欄相同。成交缺已實現
               損益時證據標 exchange_profit_reported=false，不以交易所為準。
             - find_open_event：同一 trade_id 多筆 trade_open（加碼）合併為一個部位。
             - detect_repair_candidates：加碼的交易算一筆，不再被當成兩筆略過。
             - 新 assess_repair（repair／unmappable／halt）與 expected_closing_side：
               平倉方向依開倉方向推導，支援做空。
             - 破壞性：移除 assess_auto_repair 與 render_repair_proposal_text（v2 沒有
               「提案」狀態）。momentum／seykota 在 W3／W4 重新釘選時改用執行器。
          3. 錯誤目錄 34 → 38 條：MOM／SEY.VERIFIED_CLOSE_REPAIR_FAILED（R2，取代退役的
             *_PROPOSED）、SEY.VERIFIED_CLOSE_AUTO_REPAIRED（R1）、
             SEY.VERIFIED_CLOSE_REPAIR_BLOCKED（R3）；登記冊同步新增四列（pending W3／W4）。
受影響消費專案：momentum（v2-W3）、seykota（v2-W4）重新釘選時改用執行器；在那之前
          它們釘在舊版本，不受影響。my-crypto 的 verify_and_backfill_estimated_close.py
          只用 build_evidence／build_repair_events 當計算器，重新釘選時損益差額超過 0.01
          會改用交易所數字（見上）。btc／ops-notify 不受影響。
部署入口：無（純函式庫 + 目錄資料）。
版本驗證：pyproject.toml version == 0.21.0；trade_alerts.__version__ ==
          "0.21.0"。
服務/工作流程驗證：trade-alerts pytest 全綠（見 PR）。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```

```text
trade-alerts：v0.21.1（資料修補版：錯誤目錄＋一致性登記冊，無程式變更）
變更摘要：v0.21.0 之後 src/ 只有兩份打包資料有變，本版把它們發出去，讓策略的登記冊
          自我檢查（讀已安裝套件裡的登記冊）對得上正式機現況：
          1. 錯誤目錄：MOM／SEY.VERIFIED_CLOSE_PROPOSED 從 entries 移除（retired_codes 保留，
             36 條）；6 條修復執行器代碼的 sources 改指策略呼叫點；SEY.POSITION_AMBIGUOUS
             補上市價單送出後查不到的呼叫點與追查指令（#52）。
          2. 一致性登記冊：分級 v2-W6 上正式機後的已做格子、sources 換到 momentum
             operations 3a91dd0／seykota operations f9946ba（#52）；趨勢策略重複下單事故與
             新缺口四列（#50）；通知渠道缺口兩列（#49）；趨勢策略 LINE 受控測試送達（本版）。
受影響消費專案：momentum、seykota、ops-notify 改釘 v0.21.1（全機隊同一版本）；seykota 同時
          刪除 tests/test_rollout_registry_self_check.py 的 RENAMED_AHEAD_OF_DEPLOY 豁免。
          行為不變：ops_export 渲染、修復執行器、事件日誌與 v0.21.0 相同。
部署入口：各專案既有部署腳本（開發機 → 正式機）；部署結果於改釘完成後補記於下。
版本驗證：pyproject.toml version == 0.21.1；trade_alerts.__version__ == "0.21.1"。
服務/工作流程驗證：trade-alerts pytest 全綠（見 PR）。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```
