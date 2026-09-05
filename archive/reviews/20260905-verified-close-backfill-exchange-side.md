# 審閱歸檔：build_evidence records each fill's real side, not hardcoded SELL (v0.14.1)

- **PR**：`bcup02/trade-alerts` #11
- **feature 分支**：`fix/verified-close-backfill-exchange-side`，head `196569d031e8673bc1a340766612a6c43b2cca13`
- **base**：`main` @ `512086a0f909934a819dfc7bfca03768231c2667`
- **squash 合併為**：`f69002a`（`gh pr merge --squash --delete-branch` 手動合併，trade-alerts 單分支）
- **tag**：`v0.14.1`
- **審閱者**：Perplexity — **結論 `PASS`**（無保留；1 項 non-blocking 觀察，見下）
- **CI**：`ci / pytest` = success（**129 passed**；baseline 127；+2 新測試）
- **對應 patch**：`20260905-verified-close-backfill-exchange-side.patch`

## 背景

規劃 seykota（Binance，雙向策略）要消費 v0.14.0 的共用核心時發現：
`build_evidence()` 把每一筆 deal 的 `exchange_side` 寫死成字面常數
`"SELL"`——momentum（只做多）身上剛好都對，但 seykota 有
`"SELL" if p.side == "long" else "BUY"` 這種邏輯，空單平倉的真實成交是
BUY 側，照原樣接上會把 evidence 永久性地錯標。

## 內容

- `build_evidence()` 的 `exchange_side` 改成從每筆標準化成交紀錄自己的
  `side` 欄位取值（轉大寫），只有完全沒帶 `side` 欄位時才退回 `"SELL"`。
- 對 momentum **零行為變化**——它現有的 `_precise_fill()` 本來就正確填入
  `side`（long-only close 恆為 `"sell"`），14 個既有測試逐字未改、全部
  通過。
- 新增 2 個測試：BUY-side 空單平倉正確標記、缺 `side` 欄位時維持舊
  fallback。
- 版本 patch bump `0.14.0` → `0.14.1`。

## Perplexity non-blocking 觀察

新邏輯會把任意非空 `side` 字串原樣轉大寫（例如未來某 adapter 傳入
`"close_short"`、數字 side code 或 `"unknown"`），核心不會自行拒絕或推論。
這是刻意的設計，不是這個 PR 的問題——core 的職責只是保留呼叫端已標準化、
已完成 close-side 篩選的資料；各交易所原始 side 編碼的正規化責任在
consumer adapter 層。**seykota adapter 若查到的原始資料是數字 side code，
要先在 adapter 對應成 `"BUY"`/`"SELL"` 字串再呼叫 `build_evidence()`**——
這會是 seykota 消費端 PR 的審閱重點。

## 部署

無需部署——純函式庫變更，尚未被任何消費專案 import。下一步：seykota
（Binance）+ my-crypto（MEXC）各自建薄 adapter，皆消費 `v0.14.1`。
