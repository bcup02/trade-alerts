# Perplexity 審閱歸檔 — docs: seykota trade_correction is live and the 09-21 duplicate entry is corrected (h4)

- **Repo**：bcup02/trade-alerts
- **PR**：#63，最終 head `4511888c1feeae75da7291341f07ded789414f73`
- **base**：`main` @ `f27d736`
- **squash 合併為**：`93b4da9`
- **審閱者**：Perplexity — 首審 **`PASS`**
- **CI**：pytest = success（run `35982076995`；363 passed，純資料變更 +0）
- **對應待辦**：機隊工程進度 `phase-h4`（完成）、`phase-h10`（新增）、`phase-g1`
- **部署／發版**：不發版；合併後重新發布一致性登記冊頁面。

## 做了什麼

- `ledger.trade_correction` / seykota → done：ed-seykota #69 於 2026-09-24 08:56 UTC 上正式機（operations `6d1edc2`）；
  09:02 兩段式工具寫入兩筆更正（9/18 淨損益 21.406→21.448；9/21 0.008→0.011、−10.387→−13.233）；
  09:15 兩筆 `correct_close_v2` CONFIRMED、帳本對交易所 DIVERGED→RECONCILED、LINE 真倉已實現 11.019→8.215；09:30 帳本對 Google 表 RECONCILED。
- `sources.seykota.commit` → `6d1edc2`；`FLEET.LEDGER_DIVERGED_UNIT_EXIT` seykota 引用 `compare.py:250→255`。
- `reconcile.unrecorded_fill_handling` / seykota 維持 pending（g1），只改寫 reason。
- `recent_changes` → 本格。
- 發版紀錄 v0.22.0：兩個試算表接收端都已重新部署；補趨勢策略部署時間與驗證結果；動能、維運通知改釘明寫未做（進度頁 h10）。

## 審閱

- 首審 PASS。審閱者以 ed-seykota `6d1edc2` 四個檔案的 blob SHA 與已審 PASS 的 #69 head 逐一比對（完全相同），再以 diff 行號算術確認
  `compare.py:111`、`google_ledger_provenance.py:100`、`external_trade_events.py:192`、`append_trade_correction.py:163` 逐一命中宣稱的邏輯；
  確認 `6d1edc2` 在 operations 歷史中；重算 totals（seykota done 32→33、pending 26→25）。
- 揭露的信任邊界：`registry_problems()`／`verify_registry_evidence.py` 未在審閱環境重跑（開發端為 exit 0／空）。

## 隔離聲明

只動登記冊 JSON、其產生的 HTML 與發版紀錄；無程式碼、部署或秘密變更。完整差異見同名 `.patch`。
