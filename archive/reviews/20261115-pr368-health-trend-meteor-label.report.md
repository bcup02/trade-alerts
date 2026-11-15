# PR #368 審閱歸檔：登記冊維運讀數 trend-meteor 列顯示「競賽策略・流星版」並排在主機上方

- PR：bcup02/trade-alerts #368；squash `132eade`；審閱 AI：ChatGPT；結論：一輪 PASS（head `e4076da`，CI run 43688802820，1666 passed）
- 範圍：`scripts/render_guides.py` 的 `HEALTH_TARGETS` 補 `("trend-meteor", "strategy.meteor")`、重產一致性登記冊、`tests/test_health_panel_page.py` 兩處期望值。

## 緣起
PR #366 改名後，使用者看登記冊「維運讀數」開發機表格，發現 trend-meteor 那列仍顯示原始代號，且排在主機下面：面板對不認得的對象直接顯示代號並附加在清單最後。

## 審閱歷程
| 輪 | head | 結論 | 內容 |
|---|---|---|---|
| 1 | `e4076da` | PASS | 前四個對象順序與標籤不變、新對象在主機之前；缺讀數時不產生列；HTML 與來源一致；CI 原始日誌讀不到，數字取自 sticky 摘要 |

## 已知缺口與後續
1. `scripts/render_guides.py` 第 117 行的說明仍寫「四支策略；主機只有時鐘」，現在對象有五個，待改。
2. 測試沒有直接斷言 `len(data["targets"]) == 6`，可補。

## 教訓
1. 改名或新增專案時，要連面板的對象清單（`HEALTH_TARGETS`）一起檢查；漏了不會報錯，只是顯示原始代號。
