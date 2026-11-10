# PR #353 審閱歸檔：登記冊命名統一——V11 改叫「趨勢策略」、舊趨勢標已停用並拿掉頁面欄（v0.30.31）

- PR：bcup02/trade-alerts #353；squash `60000d6`；tag `v0.30.31`（打在 squash commit）；審閱 AI：ChatGPT；結論：一輪 PASS（head `7b79a45`，CI run 42755837176，1634 passed）。
- 範圍：登記冊 `projects` 改名（trend-meteor＝趨勢策略、seykota＝舊趨勢（已停用、待封存））；名詞對照表同步；新增 `RETIRED_PROJECTS`／`ACTIVE_PROJECTS`，一致性登記冊頁面不顯示舊趨勢欄與只屬於它的 SEY.* 列，新 capability／FLEET.* 列不必填舊趨勢格（單一 owner 列仍須有格）；錯誤目錄與登記冊文字 80 處「趨勢策略・流星池版」改「趨勢策略」；兩張頁面重產；版本 0.30.31。
- 資料保留（使用者 2026-11-10 定）：舊趨勢 85 格、23 條 SEY.*、A1 驗證證據、`sources` 都沒動，待 P4 舊趨勢下線、repo 封存時整批刪。未部署 A1。

## 審閱歷程
- CI 第一次失敗：維運讀數面板 node 測試仍斷言「趨勢策略」，面板標籤取自 `strategy.seykota` 的名詞，已隨改名變成「舊趨勢（已停用、待封存）」；改測試後通過。
- ChatGPT 首審 PASS：解析產生物內嵌 JSON 核對隱藏範圍（119 項、SEY.* 0、MET.* 36）、風險頁仍 107 條含 SEY.* 23 條、80 處替換逐欄比對、`sources` 不變。

## 已知缺口與後續
1. `scripts/observation_watch.py` 3 處、程式註解、測試 docstring 仍寫舊長名「趨勢策略・流星池版」；改了要重新部署開發機偵測，另排。
2. 錯誤目錄 SEY.* 與舊程式文字裡的「趨勢策略」指的是舊趨勢，沒有逐條改。
3. 審閱建議（非阻擋）：補兩個變異測試——刪掉 FLEET.* 一個活躍 owner、status 插入未知 owner，直接驗證上下界兩側。
4. P4 舊趨勢下線、repo 封存時，整批刪 `seykota` 格、SEY.* 條目與 `RETIRED_PROJECTS`。

## 教訓
1. 名詞對照表的 zh 改名會連動所有以名詞取標籤的地方（維運讀數面板、node 測試）；改名前先 grep `strategy.<id>` 與斷言舊名的測試。
2. 「拿掉欄」要先分清是頁面還是資料：使用者選頁面不顯示、資料留著，驗證只放寬必填、不放寬單一 owner。
