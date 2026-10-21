# 審閱歸檔：觀察區偵測移除 crypto-flat 檢查（PR #263）

- PR：bcup02/trade-alerts #263；squash `ed30a39`（main）
- head `c9abee2d4b2ff506c7fb1ae7ce12197c1dec221d`；base `f4a555957ff666e3c1090bf65aa374d959770432`
- 審閱：1 輪（ChatGPT），PASS。CI：run 39647950749（1212 passed，前次 1215，差 -3＝移除 4 個 crypto-flat 測試、新增 1 個孤兒狀態測試）。

## 重點
- 移除 `crypto-flat` 檢查（唯一用途是提醒開始 x1 換 Binance，x1～x8 已於 2026-10-13～10-17 完成，進度頁 phase-x1 為 done）。沒有其他用途，所以直接移除而非停用。
- `run_checks()` 只保留目前仍在 `checks` 的 id，已移除檢查的舊 state 項目在下一次完整 `run` 自動清掉，不必手動改 state.json。
- 原本靠 crypto-flat 驅動的通用機制測試（run/report/ack、鎖、LINE→Telegram）改用 `a1-crypto-equity`；新增孤兒狀態測試。

## 限制
- `run --only <id>` 仍會保留舊項目（`main()` 既有合併邏輯），只有完整 `run`（排程用的）才會清。
- 測試只到 `run_checks()` 層，沒有 `main()` 寫檔再讀回的端對端孤兒清除測試（審閱者列為日後補強）。

## 部署
- 2026-10-22 台北約 02:14 部署到 A1-dev（只換 /opt/observation-watch/observation_watch.py）；手動跑一輪成功，`report` 已無 crypto-flat；未碰 A1 正式機。

## 隔離聲明
審閱端只讀 GitHub 程式碼、提交差異與 CI 日誌；未碰 /opt、/etc、systemd、交易所、Google 或 A1；未 checkout、未 push。
