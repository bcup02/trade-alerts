# PR #398 審閱歸檔：對帳——沒有真倉交易且表上也沒有交易列＝一致（v0.30.48）

- PR：bcup02/trade-alerts #398；squash `8b6c483`；審閱 AI：ChatGPT；結論：第 1 輪 BLOCK（head `3b9dd2b`，base `e660440`）、第 2 輪 PASS（head `faad111`，CI run 44463266164，1683 passed）；tag `v0.30.48`。
- 範圍：`ledger_reconcile.sheet_ledger_compare` 新增 kw-only `ledger_readable`（預設 False）；空 trades 且沒傳旗標＝與舊版逐字相同的 UNKNOWN；傳旗標、表讀成功、表上沒交易列＝RECONCILED，表上有帳本不認得的交易列＝DIVERGED（LEDGER_MISSING_ROW）。不動「帳本↔交易所」的空帳本判定；另外三支策略不傳旗標、行為不變。

## BLOCK-398-01（已修）
第一版直接拿掉「空 trades 就回 UNKNOWN」。`read_ledger` 對不存在或讀不了的檔回 `[]`，空 trades 分不出「從沒交易」與「帳本遺失」，帳本遺失加空表會被判 RECONCILED（fail-open）。第 2 輪改成預設仍 UNKNOWN，由呼叫端明確聲明「確實讀到一個存在的帳本」才放行；新增測試重現審閱者情境（`read_ledger` 不存在的檔→`fold_ledger_trades`→空 trades→不傳旗標＝UNKNOWN）。

## 後續（審閱者列為下一個 PR 的必查條件）
流星版轉接層（趨勢 repo `google_reconcile.run`）傳 `ledger_readable` 時，必須先確認帳本快照檔確實存在、讀取成功且品質檢查沒問題；不能只以 `read_ledger()` 回空清單當成功證據。

## 教訓
1. 把「資料不足的 UNKNOWN」改成肯定答案之前，先問「輸入為空」有幾種成因（沒交易、檔案遺失、讀不了）；共用庫的輸入若已經把這些成因壓成同一個值，要加上呼叫端的來源完整性聲明，預設走保守答案。
