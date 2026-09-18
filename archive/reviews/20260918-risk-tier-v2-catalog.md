# 審閱歸檔：錯誤目錄 v2 — 四級分級、33 條白話說明（W1a，v0.19.0）

- **PR**：`bcup02/trade-alerts` #29，head `43568716f30042da61695d5eac8a1c1ec83fa698`
- **base**：`main` @ `7da5315`
- **squash 合併為**：`31cf9b1`，tag `v0.19.0`
- **審閱者**：Perplexity — 首審 **`PASS`**（一輪；附四項它拿不到其他 repo 而無法核實的跨 repo 宣稱，開發端已逐項查證，見下）
- **CI**：`pytest` = success（run `35297104503`；232 passed，baseline 229）
- **部署**：不需要（純函式庫＋目錄資料）
- **計畫**：`~/.claude/plans/r0-r4-r1-r2-r3-r4-r2-r3-r1-r2-r3-r1-zazzy-bear.md` 的 W1a

## 這一支做了什麼

使用者 2026-09-18 拍板把錯誤分級由五級改四級：R0 只記錄／R1 自動不通知（舊 R2）／R2 自動嘗試、連續 3 次失敗才升格通知
（舊 R1＋舊 R3）／R3 必須人工（舊 R4）。v1 的「提案」「逾時自動執行＋Telegram 提早核准」「事後稽核通知」全部取消。

- 目錄改名 `fleet-error-catalog-v2.json`，33 條逐條重新分級；語意改變的條目改寫目標行為；`retired_codes` 列出
  `MOM.VERIFIED_CLOSE_PROPOSED` 與 `SEY.VERIFIED_CLOSE_PROPOSED`（後者 seykota 影子 bot 一直在發、v1 從未登記）。
- 33 條全部補 `operator_message`（v1 只有 3 條），R2/R3 加 `ai_prompt`。
- seykota 孤兒停損單自動取消加兩道安全條件（只取消自己記錄的舊單編號＋先確認新保護單已在交易所上）。
- 程式：`RISK_TIERS` 四級、`REQUESTABLE_TIERS` = {R2, R3}、`ops_export` 只匯出 R3 與升格的 R2（`needs_human`，嚴格 `is True`）、
  訊息附 AI 追查指令＋事件識別資料；`fleet-ops-export/v2`。

## 審閱結論：PASS

七項逐項核對：v1→v2 映射以完整 diff 逐條比對零例外；治理不變式本體未改弱；v1 概念只在標示為歷史說明處出現；
本 PR 不含任何下單／取消程式碼，所以安全條件目前只是規格（實作時要再審）；`needs_human` 為嚴格布林；
改寫的既有測試是擴大而非弱化。

## 審閱者無法核實的跨 repo 宣稱 — 開發端查證結果

1. **seykota RECONCILE_FAILED／RUNTIME_CYCLE_FAILED 已實作「重試、連續 3 次才 latch」**：屬實。
   `ed-seykota-systematic-trend-following/src/seykota_bot/bot.py` 第 46、123 行起的 Phase 4d 連續失敗計數器。
2. **`seykota-resume` CLI 存在**：屬實。`pyproject.toml:41` `seykota-resume = "seykota_bot.safe_halt_resume:main"`，
   子命令 `preview`／`resume --confirm --exchange-verified`；/opt 的 venv 已有該執行檔。
3. **seykota「改好設定重啟也清不掉暫停」缺陷**：屬實，而且確認了機制。`safe_halt_resume.py:59-62` 把 EXCHANGE_TARGET_UNSAFE／
   FIXED_IDENTIFIER_CONTRACT_UNAVAILABLE 列為 `RESTART_ONLY_CODES` 並在 :103 拒絕解除；`bot.py` 的 docstring（:357-360）說這兩類
   靠「改設定＋重啟」清除，但 `run_once` 守衛通過後直接走到 `if self._is_latched(): return`（:1553 附近），整個 bot 只有
   `_clear_automatic_safe_halt` 清 FLATTENED 那一類——**沒有任何程式會清掉這兩類 latch**，只能手改 state 檔。
   列入一致性登記冊待修。
4. **momentum 釘 v0.18.0、ops-notify 讀 export v1**：屬實（momentum `pyproject.toml:37`；ops-notify `export_relay.py:36`）。

另：審閱者回報連接器讀 `docs/perplexity-review-sop.md` 只拿到 SHA、拿不到內文，改照審閱指令展開的格式執行。

## 隔離聲明

未接觸 `/opt` `/etc` `/var/lib`、systemd、交易所、Google、實機帳本；無 token/密鑰；未觸發部署。
