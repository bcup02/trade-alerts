# 審閱歸檔：`recent_changes` 支援 `type: added`（新增一整列）；畫面統一叫「🆕 最新變動」、單一金黃色

- **PR**：`bcup02/trade-alerts` #39，head `7cbbd87b3953f1cad4f71893eab627dfcb103e74`
- **base**：`main` @ `86e45cd`
- **squash 合併為**：`6bc042d`
- **審閱者**：Perplexity — **`PASS（兩輪：首審 PASS 附一項非阻斷建議，補合成測試後複審 PASS）`**
- **CI**：`pytest` = success（run `35369745580`；281 passed（+4））
- **部署**：不需要（trade-alerts 是純函式庫／資料＋靜態頁；頁面已重新發布到 Artifact）

## 為什麼做

#38 只新增一列未完成紀錄、沒有格子變已做，開發端當時沒清空 `recent_changes`，導致頁面「最新變動」停在兩輪前的舊內容——正是這個機制要防的失效。使用者要求不分兩種顏色，統一叫最新變動。

## 審閱重點

首審：分流邏輯、schema 的 `not`+`required` 條件式、視覺只有一種都正確；指出真實資料只剩 added 類型，completed 的渲染路徑失去回歸保護。複審：新增不依賴真實資料的合成測試，確認鎖住該路徑、非恆真，缺口已補。

## 隔離聲明

變更只在 trade-alerts 的 `src/trade_alerts/`、`schemas/`、`scripts/`、`tests/`、`docs/` 範圍；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或正式機帳本，無密鑰。完整差異見同名 `.patch`。
