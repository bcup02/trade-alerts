# 機隊系統手冊 / 文件

跟 `docs/` 其他檔案（`fleet-error-catalog.md`、`branch-governance.md` 之類）不同——那些是給 Claude／
Perplexity／開發者看的工程規格與流程規則。這個目錄放**給人看的成品**：白話說明、操作手冊、視覺化頁面，
橫跨四支策略、不屬於任何一支的程式碼。

## 目前收錄

| 檔案 | 說明 | 對應資料源 |
|---|---|---|
| `fleet-risk-register.html` | 機隊風險登記冊——33 種已知錯誤情況，依四個風險等級（v2）白話說明、處理步驟與給 AI 的追查指令，並標示各策略實際做到了沒有；可依等級／策略／未做完篩選。 | `src/trade_alerts/catalog/fleet-error-catalog-v2.json`＋`fleet-rollout-registry.json` |
| `fleet-rollout-register.html` | 機隊一致性登記冊——每項機隊功能與每條錯誤規則在四支策略的已做／未做（含預定哪一關）／不適用（含理由）；分「未完成／已完成」兩組，最上方目錄可點擊跳到該項，已完成項目預設摺疊，右下角有回到最上方按鈕。JSON 的 `recent_changes` 可以標出這次更新剛變成已做／不適用的格子，頁面用「🆕 最新完成」黃色標示並列在最上方的「最近變動」欄，同時兼作「這次更新有沒有真的生效」的視覺確認。 | `src/trade_alerts/catalog/fleet-rollout-registry.json` |

## 慣例

- 純 HTML／Markdown，靜態頁面即可開啟，不依賴任何後端。
- 每份文件盡量在檔案開頭或這份 README 的表格裡標注「對應到哪個資料源」，資料源更新後回頭核對這份文件
  有沒有跟著過期。
- **上表兩個 HTML 頁面由 `scripts/render_guides.py` 從 JSON 產生，不可手改**（v1 風險登記冊就是因為
  手寫第二份而漏掉 3 條）。改資料源後執行 `python scripts/render_guides.py`；
  `tests/test_rollout_registry.py` 會比對 repo 內的頁面與重新產生的結果，不一致 CI 就紅。
- 這裡是**版本控管的備份**，不是即時互動版。互動版（可篩選、有 hover 效果的那個）發布在 Claude 的
  Artifact 平台，連結由開發時的對話記錄保存；這裡的檔案是同一份內容的靜態快照，供離線查閱與 git 歷史
  追蹤。
- 純文件變更（不動 `src/` 底下任何程式碼）依既有慣例豁免 Perplexity 審閱，可直接合併。
