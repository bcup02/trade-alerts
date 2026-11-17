# PR #370 審閱歸檔：Google 表「出場原因」欄補上競賽策略・流星版五個來源代碼中文（v0.30.38）

- PR：bcup02/trade-alerts #370；squash `5b13ae3`（tag `v0.30.38`）；審閱 AI：ChatGPT；結論：一輪 PASS（head `e73ea19`，CI run 44014691904，1666 passed）
- 範圍：名詞對照表「帳本來源代碼」補 `entry`、`exit`、`recovery`、`intraday_stop`、`verified_close` 五條；重產接收端 `EXIT_REASON_ZH` 區塊與登記冊頁面；版本 0.30.38。

## 緣起
使用者看 Google 表「趨勢策略」分頁（開發機接收端）的「出場原因」欄，第 6 列顯示 `verified_close` 原始代碼。競賽策略・流星版帳本的五個 source 值都不在對照表，接收端查不到就原樣顯示，正常的進出場列之後也會一樣。

## 審閱歷程
| 輪 | head | 結論 | 內容 |
|---|---|---|---|
| 1 | `e73ea19` | PASS | 五條中文與 `ledger_sink.py` 語意一致；34 個代碼無重複、接收端 34/34 一致；`.gs` 只動對照區塊；CI 原始日誌 1666 passed |

## 已知缺口與後續
1. 接收端腳本尚未部署（先 DEV、再正式，要先問使用者）；部署後已寫入的舊列要先跑 `previewExitReasonConversion()` 預覽，再由使用者決定是否套用。
2. 接收端對照是全域的，不分專案；`entry`、`exit`、`recovery` 若其他策略也寫入，會顯示同一個中文。現有對照表沒有同代碼不同中文的衝突，但 Google 表所有歷史列沒有逐一稽核。

## 教訓
1. 新專案的帳本 source 值要在開工時就比對名詞對照表；漏了不會報錯，只是 Google 表顯示代碼。
