# 審閱歸檔：exchange-agnostic verified-close-backfill core (v0.14.0)

- **PR**：`bcup02/trade-alerts` #10
- **feature 分支**：`feature/verified-close-backfill-core`，head `80a1a78fb6245ddd40d015028c722dcea1778115`
- **base**：`main` @ `f78576cbaae97e430b9db7f02cae0761bbf08152`
- **squash 合併為**：`aa859b1`（`gh pr merge --squash --delete-branch` 手動合併，trade-alerts 單分支）
- **tag**：`v0.14.0`
- **審閱者**：Perplexity — **結論 `PASS`**（無保留；附 3 項非阻擋後續建議，見下）
- **CI**：`ci / pytest` = success（**127 passed**；baseline 113；+14 新測試）
- **對應 patch**：`20260905-verified-close-backfill-core.patch`

## 背景

三個實盤交易專案（momentum/seykota/my-crypto）各自都需要「verified-close
back-fill」修復工具：策略部位追蹤在交易所端查不到某部位時會「推定已平倉」
釋放名額、留 pending 標記，但如果那個部位其實還開著、之後才真的平倉，本地
帳本會留下有真實 qty 卻沒 close 的部位落差，`reconcile_apply.py` 明確拒絕
處理這種情況。

momentum 已在 PR #52 建好這個工具，但 `build_evidence()` 內部直接假設
Binance 原始 API 欄位名稱（`qty`/`commission`/`realizedPnl`），且補帳本事件
的 `reconciliation.method` 欄位寫死 `"read_only_mexc_history_orders_and_deals"`
——momentum 現在明明是 Binance，這是遷移後留下的錯誤標籤（只自我引用，
無下游依賴，修正安全）。使用者明確要求：不要把交易所綁死在任何一支專案的
工具裡（三個專案都已各自換過至少一次交易所）。

## 內容

- 新模組 `verified_close_backfill.py`：完全不 import 交易所 SDK、不建構任何
  專案自己的 `TradeLedger`。`build_evidence()` 吃已標準化的成交紀錄（跟
  `binance_reconcile_fetch.fill_rows()` 輸出的 `reconcile-source/v1` 格式
  一致），`method` 改成參數（由呼叫端傳入，缺值時退回中性標籤而非猜測交易所）。
  `load_evidence`/`build_repair_events`/`append_repair`/`find_open_event`/
  `REPAIR_EVENT_TYPES` 邏輯逐行對照 momentum 現有 `append_reconciled_close.py`
  搬過來，數學完全不變。`append_repair` 改成接受注入的 `ledger_append`
  callable，不再自己建構 `TradeLedger`。
- `binance_reconcile_fetch.py`：`_position_rows`/`_fill_rows` 改名為公開的
  `position_rows`/`fill_rows`，純改名零邏輯變動。
- 測試：新測試檔對照 momentum 現有兩個測試檔的覆蓋，`append_repair` 部分
  直接搬用 momentum 真實歷史證據檔案（`mubarak-20260820-exchange-evidence.json`，
  MEXC 時代真實事故證據）當 fixture 逐位元組核對——證明補帳本邏輯本來就
  跟交易所無關，也向後相容缺 `method` 欄位的舊格式證據。
- 版本 `0.13.4` → `0.14.0`。

**這個 PR 刻意不做的事**：不改 momentum/seykota/my-crypto 任何消費專案；
`fetch_verified_close_evidence.py`/`append_reconciled_close.py` 的重構是
下一個獨立 PR。

## Perplexity 非阻擋後續建議（consumer 整合 PR 要記得）

1. consumer 整合 PR 應新增「adapter 把交易所原始成交正確正規化成 core
   contract」的測試，特別是 side filter、symbol mapping、查詢時間窗、
   partial-fill 加總。
2. consumer 整合 PR 應明確測試 `ledger_append` 綁定到各自
   `TradeLedger.append` 後的 event_id、timestamp、execution_mode 等
   project-specific 必要欄位。
3. 核心 `build_evidence()` 刻意不檢查 fill 的 `side` 值——假設呼叫端已完成
   交易所專屬的 side 正規化與篩選（只傳入 closing-side 的 fills）。這是
   合理的 adapter/core 職責切分，但 consumer 整合時不能遺漏這一步。

## 部署

無需部署——這是純函式庫變更，尚未被任何消費專案 import。下一步：momentum
的 `fetch_verified_close_evidence.py`/`append_reconciled_close.py` 重構成
吃這個新核心（獨立 PR，需嚴格比對行為零變化），之後 seykota（Binance）+
my-crypto（MEXC）建各自的薄 adapter。
