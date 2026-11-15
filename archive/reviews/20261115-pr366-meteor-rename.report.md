# PR #366 審閱歸檔：V11 與流星池版統一改名「競賽策略・流星版」

- PR：bcup02/trade-alerts #366；squash `cbc923c`；tag `v0.30.37`（打在 squash commit）；審閱 AI：ChatGPT；結論：一輪 PASS（head `b0e501f`，CI run 43684887752，1666 passed）
- 範圍：只改中文顯示名，沒有改邏輯；程式代號 trend-meteor、MET.、單元名、Google 表分頁名「趨勢策略」、指舊趨勢的「趨勢策略」刻意不動。

## 緣起
2026-11-15 使用者定：原「趨勢策略（V11）」與「競賽策略・流星池版」是同一支，統一叫「競賽策略・流星版」（五個 repo 同步：trade-alerts #366、fleet-backtest #87、ed-seykota #246、portfolio-query #41、ops-notify #76）。

## 審閱歷程
| 輪 | head | 結論 | 內容 |
|---|---|---|---|
| 1 | `b0e501f` | PASS | 審閱者逐項確認識別字零變更、測試零刪除零改弱；CI 原始日誌讀不到，數字取自 sticky 摘要 |

## 已知缺口與後續
1. 開發機要重裝／重部署，顯示名才會變；開發機既有設定若覆寫了名稱（ops-notify 環境檔的標籤、portfolio-query 的 presentation.toml）要另外查。
2. Google 表分頁名「趨勢策略」仍是舊名，要不要改另案。

## 教訓
1. 改名後原本「覆寫值不同於預設值」的測試會變成同值，要改用另一個值才真的驗到覆寫。
2. 顯示名改名前，先確認去重與提醒計次用的是固定的專案代號，不是顯示名。
