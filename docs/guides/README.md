# 機隊系統手冊 / 文件

跟 `docs/` 其他檔案（`fleet-error-catalog.md`、`branch-governance.md` 之類）不同——那些是給 Claude／
Perplexity／開發者看的工程規格與流程規則。這個目錄放**給人看的成品**：白話說明、操作手冊、視覺化頁面，
橫跨四支策略、不屬於任何一支的程式碼。

## 目前收錄

| 檔案 | 說明 | 對應資料源 |
|---|---|---|
| `fleet-risk-register.html` | 機隊風險登記冊——30 種已知錯誤情況，依五個風險等級白話說明，可依等級/策略篩選。 | `src/trade_alerts/catalog/fleet-error-catalog-v1.json` |

## 慣例

- 純 HTML／Markdown，靜態頁面即可開啟，不依賴任何後端。
- 每份文件盡量在檔案開頭或這份 README 的表格裡標注「對應到哪個資料源」，資料源更新後回頭核對這份文件
  有沒有跟著過期。
- 這裡是**版本控管的備份**，不是即時互動版。互動版（可篩選、有 hover 效果的那個）發布在 Claude 的
  Artifact 平台，連結由開發時的對話記錄保存；這裡的檔案是同一份內容的靜態快照，供離線查閱與 git 歷史
  追蹤。
- 純文件變更（不動 `src/` 底下任何程式碼）依既有慣例豁免 Perplexity 審閱，可直接合併。
