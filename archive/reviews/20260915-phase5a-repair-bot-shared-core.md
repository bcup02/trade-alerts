# 審閱歸檔：Phase 5a repair-bot shared core (send_text bool + detection + proposal text)

- **PR**：`bcup02/trade-alerts` #20
- **feature 分支**：`phase5a-repair-bot-shared-core`，head `f01a5b5a72e195248240da0ebb7dd491c3252e24`
- **base**：`main` @ `faf371d`
- **squash 合併為**：`5a051c1`（`gh pr merge --squash --delete-branch`）
- **審閱者**：Perplexity — **結論 `PASS`**（連結器直讀，一輪）
- **CI**：`pytest` = success（run `34975221739`；169 passed，baseline 161，+8 新測試）
- **對應 patch**：`20260915-phase5a-repair-bot-shared-core.patch`
- **部署**：不需要（trade-alerts 是純函式庫，無執行期足跡；version 0.15.0 → 0.16.0）

## 背景

8-Phase 錯誤處理重建計畫 Phase 0-4 全數完成並上真倉（2026-09-15）。Phase 5「修復 bot 影子模式」
是計畫定義的下一步：把「偵測→抓證據→算出完整修復→寫事件日誌→**這時才發 LINE 通知（附提案）**」
串成一支影子模式 bot，verified-close-backfill 是這個平台的第一個租戶。盤查發現 momentum/seykota
已有手動 CLI 工具（`fetch_verified_close_evidence.py` + `append_reconciled_close.py`）與可重用的
純函式（`build_evidence`/`build_repair_events`/`append_repair(apply=False)`），但缺兩塊地基：
通知送達確認（`send_text` 回傳 `None` 不是 `bool`，已知缺口）與「symbol 級數量差→候選 trade_id」
的偵測邏輯。這支 PR 補這兩塊，是 Phase 5 拆成的四個子階段（5a-5d）裡的第一個，純函式庫、無部署
足跡。

## 這一支做了什麼

1. `AlertDispatcher._send_text`／`publish`／`publish_contract`／`test`（`core.py`）：回傳型別
   `None` → `bool`（是否至少一個 channel 送達）。單一 channel 失敗仍只記 log、不中斷其他
   channel。既有呼叫端忽略回傳值不受影響。是 Phase 7「計時器只在通知確認送達後才開始倒數」的
   地基，提前修不用等到 Phase 7。
2. `verified_close_backfill.py` 新增兩個純函式：
   - `detect_repair_candidates(ledger_status, ledger_events)`：把 `reconcile_compare.py` 的
     `DIVERGED` 判定裡 `evidence.position_diffs` 的 symbol 級數量差，換算成候選 `trade_id`（該
     symbol 唯一還沒 `trade_close` 的 `trade_open`）。symbol 不在 diff、已有 close、或同 symbol
     有 ≥2 筆未結案 `trade_open`（歧義）都回傳空——只在無歧義時給答案。正是
     `reconcile_apply.py` 目前明確拒絕、留給「之後的 PR」處理的那個 case。
   - `render_repair_proposal_text(evidence, repair_events, project)`：把 `build_repair_events()`
     算出的完整修復內容組成人看得懂的 LINE 通知文字，對應 R1 `PROPOSE` 語意（算出方案才通知、
     附提案）。純字串組裝，不呼叫任何 channel、不寫任何東西。
3. 版本 bump 0.16.0 + `docs/consumer-release-runbook.md` 發布紀錄條目。
4. **刻意不改**：`append_repair`／`build_evidence`／`build_repair_events` 本身邏輯未動；
   `channels.py`（Telegram/LINE 底層 `send()`）未動，成功/失敗判定仍是「有沒有拋例外」。

## Perplexity 審閱（一輪 PASS，逐項核對）

- **通知 bool 語意**：確認是「至少一個 channel 成功」而非「全部成功」，四種情境（多管道皆
  送達/部分送達/全部失敗/無 channel）逐一對照程式碼與測試，語意保守且合理。向下相容性確認：
  忽略回傳值的既有呼叫端控制流程不變。
- **`detect_repair_candidates` 無歧義判定**：五種情境（唯一候選/symbol 不在 diff/已有
  close/兩筆未結案 trade open/非 DIVERGED）逐一對照程式碼與對應測試，確認 0 筆與 ≥2 筆都正確
  回傳空、不猜。
- **`render_repair_proposal_text` 零副作用**：確認純字串函式，不 import channel/dispatcher/
  filesystem/network/ledger writer/event log，測試用真實 evidence fixture 驗證關鍵欄位（
  trade_id/symbol/net_pnl/exchange_profit/method）都出現在輸出。
- **回歸**：`append_repair`/`build_evidence`/`build_repair_events` 定義本身未修改，既有測試
  原封不動，只新增 import 與 8 個新測試。公開 API（`__init__.py` re-export + `__all__`）同步
  更新。
- **隔離聲明**：僅讀取 PR metadata/diff/CI，未接觸 `/opt` `/etc` `/var/lib`、systemd、交易所、
  Google、實機帳本，未寫入任何內容。

## 依賴關係

Phase 5b（momentum 影子模式 bot + 部署）與 5c（seykota 影子模式 bot + 部署）會 bump pin 到
`trade-alerts` v0.16.0，並直接呼叫這支 PR 新增的 `detect_repair_candidates`／
`render_repair_proposal_text`。在那之前四支策略照舊運作，這支 PR 本身無立即消費者。
