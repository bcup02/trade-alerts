# 名詞對照表：搬家期間區分兩台正式機

- PR：[bcup02/trade-alerts#81](https://github.com/bcup02/trade-alerts/pull/81)，squash 合併 `31acdc0`（base `440881b`）
- Perplexity：首審 **PASS**（head `99d8a6f`）
- CI：pytest 381 passed（run 36556064031）

## 內容

使用者 2026-09-29 要求：到 trading-main 除役前，指主機一律講清楚。名詞對照表新增「A1 正式機（新）」（fleet-prod-tokyo、161.33.186.220）
與「trading-main 正式機（舊）」（trading-main）；「正式機」改指角色，單寫只用於角色或正式機分支；註明登記冊「已做」在切換完成前
指 trading-main 正式機（舊）上在跑。一致性登記冊頁面重新產生（48→50 條）。規則同步寫進工作區 CLAUDE.md 第 5 段。

## 審閱重點

非阻擋：`host.main` 與 `host.main.gcp` 的 en 都含 trading-main，目前頁面以 id 作錨點不受影響；日後工具若要由 en 反查詞條，應改用 id。
切換、除役後要照 note 更新詞條，「新／舊」不得永久沿用。

## 隔離聲明

審閱只讀 GitHub；只改對照表資料與產生頁，沒有接觸任何主機、服務、交易所或帳本。
