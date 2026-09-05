# 審閱歸檔：gross_pnl direction fix for a short-position close (v0.14.2)

- **PR**：`bcup02/trade-alerts` #12
- **feature 分支**：`fix/verified-close-backfill-short-pnl-direction`，head `777202a0c9a494ff8b355cde3e9eebf00e4fc317`
- **base**：`main` @ `d17241b59003ca76e92c7de718da476b129759f4`
- **squash 合併為**：`4c65ce1`（`gh pr merge --squash --delete-branch` 手動合併，trade-alerts 單分支）
- **tag**：`v0.14.2`
- **審閱者**：Perplexity — **結論 `PASS`**（無保留）
- **CI**：`ci / pytest` = success（**132 passed**；baseline 129；+3 新測試）
- **對應 patch**：`20260905-verified-close-backfill-short-pnl-direction.patch`

## 背景

規劃 seykota adapter 時發現：`build_repair_events()` 的
`gross_pnl = (exit_price - entry_price) * exit_volume * contract_size`
無條件套用多單公式。seykota 雙向都做，空單平倉的正確公式方向相反。

## 內容

- 方向從平倉成交自己的 `exchange_side`（v0.14.1 剛修好）判斷：**只有明確
  `"BUY"` 才翻轉成空單公式**；其他任何值（`"SELL"`、無法辨識的字串、
  v0.14.0 之前的舊 evidence 帶的 MEXC 數字 side code）一律維持原本多單
  公式——刻意設計成「明確訊號才 opt-in 新行為」而非「模糊訊號就 opt-out
  舊預設值」。
- **誠實揭露的踩坑記錄**：第一次寫的邏輯剛好相反（預設當多單、只有
  明確 `"SELL"` 才維持原公式），結果直接把真實 MUBARAK 黃金證據檔案
  （`exchange_side` 是 MEXC 數字代碼 `3`）的方向算錯（`net_pnl` 從
  `-0.1828984` 變成 `0.1631016`），被既有測試當場抓到，修正後才提交
  PR——這正是「先讓測試抓、不是靠人工檢查」這個模式的第三次示範
  （見 [[project_verified_close_backfill_toolkit]] memory 累積的教訓）。
- 新增 3 測試：空單平倉在價格下跌時獲利（真正修的 bug）、多單平倉
  在價格上漲時獲利維持不變、真實 MUBARAK 舊格式證據檔案的數字
  side code 仍正確走多單公式。
- 版本 patch bump `0.14.1` → `0.14.2`。

## 部署

無需部署——純函式庫變更。這是 seykota adapter PR 送審前，trade-alerts
端修的第 3 個 bug（exchange_side 標記 v0.14.1、gross_pnl 方向 v0.14.2，
加上 v0.14.0 的 momentum 例外契約問題），至此雙向策略的數學跟稽核標記
都已正確，seykota adapter 可以開始送審。
