# PR #375 審閱歸檔：讀表可用 project_id 找分頁、分頁名稱允許「・」（v0.30.40）

- PR：bcup02/trade-alerts #375；squash `262d134`（tag `v0.30.40`）；審閱 AI：ChatGPT；結論：第 1 輪 BLOCK、第 2 輪 BLOCK（只缺新 base 的 CI）、第 3 輪 PASS（head `002a219`，CI run 44136696969，1675 passed）。
- 範圍：`ledger_reconcile.fetch_sheet_rows` 新增 `project_id`（與 `sheet_name` 恰好給一個）；`ledger_integrity` 分頁名稱白名單加入 U+30FB（非首字）；版本 0.30.40。

## 審閱歷程
| 輪 | head | 結論 | 內容 |
|---|---|---|---|
| 1 | `584f284` | BLOCK | `sheet_name` 路徑的 payload 鍵插入順序變了（secret、action、sheet_name），與舊版位元組不同；原測試用字典相等，看不出順序 |
| 2 | `f94e858` | BLOCK | 程式 PASS；但 main 已前進（#374 合併），CI 驗的是舊 base |
| 3 | `002a219` | PASS | 分支疊到新 main，六檔與上輪逐位元組相同，新 base 的 CI 綠燈 |

## 已知缺口與後續
1. 純空白字串的 selector 不拒絕（契約是「非空字串」）。
2. 沒有對「競賽策略・流星版」做 `verify_signed_request` 的直接驗證（簽章流程未改）。
3. 流星版程式尚未改用（下一個 PR）；DEV 接收端 v0.30.39 已部署，正式機未部署。

## 教訓
1. 宣稱「逐字相同」的測試要比序列化後的字串，字典相等不檢查鍵順序。
2. 審閱期間 base 前進，要把分支疊上去重跑 CI 再給審閱者核對檔案相同，不能拿舊 base 的綠燈當數。
