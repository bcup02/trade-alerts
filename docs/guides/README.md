# 機隊系統手冊 / 文件

跟 `docs/` 其他檔案（`fleet-error-catalog.md`、`branch-governance.md` 之類）不同——那些是給 Claude／
審閱 AI／開發者看的工程規格與流程規則。這個目錄放**給人看的成品**：白話說明、操作手冊、視覺化頁面，
橫跨四支策略、不屬於任何一支的程式碼。

## 目前收錄

| 檔案 | 說明 | 對應資料源 |
|---|---|---|
| `fleet-risk-register.html` | 機隊風險登記冊——34 種已知錯誤情況，依四個風險等級（v2）白話說明、處理步驟與給 AI 的追查指令，並標示各策略實際做到了沒有；可依等級／策略／未做完篩選。 | `src/trade_alerts/catalog/fleet-error-catalog-v2.json`＋`fleet-rollout-registry.json` |
| `fleet-rollout-register.html` | 機隊一致性登記冊——每項機隊功能與每條錯誤規則在四支策略的已做／未做（含預定哪一關）／不適用（含理由）；分「未完成／已完成」兩組，最上方目錄可點擊跳到該項，已完成項目預設摺疊，右下角有回到最上方按鈕。JSON 的 `recent_changes` 標出這次編輯真正動到的東西（一格變成已做／不適用是 `type: completed`，新增一整列是 `type: added`），頁面上不分兩種、統一用「🆕 最新變動」黃色標示並列在最上方摘要欄，兼作「這次更新有沒有真的生效」的視覺確認——**每次編輯登記冊 JSON 都要同步整份換掉這個欄位，不是累加，沒有東西要標就設成 `[]`**。最上方有「維運讀數」面板（f-45，見下方說明）；頁面最下方另有「名詞對照表」（全專案統一中文名、對應英文代號、不要再用的舊叫法）；`tests/test_fleet_glossary.py` 會掃描本 repo 給人看的文字，出現舊叫法就擋。 | `src/trade_alerts/catalog/fleet-rollout-registry.json`＋`fleet-glossary.json` |
| `health-sheet-setup.md` | 維運讀數試算表與 Apps Script 專案的建置清單（f-45）：為什麼要獨立的小試算表、A 段（不碰主機，使用者建）、B 段（主機上，等 x7 觀察期滿）、常見問題。手寫文件，不是產生頁。 | 進度頁 f-45、`apps_script/google_ledger_receiver.gs` |
| `oracle-migration-plan.md` | 正式機從 GCP 搬到 Oracle 東京 ARM 主機的搬家計畫（f-2c）：已驗證事項、要搬的東西、待查證清單、切換四階段、退回方式、開發機去留。手寫文件，不是產生頁。 | 進度頁 f-2、各 repo 部署腳本 |

## 一致性登記冊最上方的「維運讀數」面板（f-45）

- 顯示一台主機上 ops-notify 最新一輪讀數（對象 × 軸的矩陣）。資料由該主機的發布單元每 10 分鐘寫進一份**只有一個分頁「維運健康」、A1 一格**的獨立 Google 試算表，頁面用**檢視者自己的 Google Drive 連接器**（`read_file_content`）讀回來；這就是頁面宣告的唯一連接器能力（`render_guides.HEALTH_CAPABILITIES`，發布頁面時要帶），用到連接器的頁面不能公開分享。
- 讀哪份試算表在 `src/trade_alerts/catalog/fleet-health-sources.json`：`file_id` 是 `null` 時面板只寫「還沒設定讀數來源」、完全不呼叫連接器；填入 Drive 檔案編號後重新產生頁面並重發。主機名稱由名詞對照表（`host_term`）取得。
- 解析與「什麼可以叫正常」的邏輯全在 `scripts/health_panel_core.js`（純函式，頁面與 `tests/health_panel_node_test.js` 載入同一個檔案；`tests/health_panel_page_node_test.js` 用假的 DOM 和假的連接器跑整個頁面）。三個時間各管一種「停止更新」：`generated_at`（發布單元）超過 25 分鐘、`checked_at`（輪詢）超過 45 分鐘、單格 `checked_at` 超過 45 分鐘就標過期，過期的格子灰掉、不顯示成正常；讀數時間是 `null`（讀不到，f-62）標「無讀取時間」。
- 儲存格內容是不可信資料：結構逐項驗證、長度有上限、一律用 `textContent`，不會變成標記。

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
- 純文件變更（不動 `src/` 底下任何程式碼）依既有慣例豁免審閱 AI 審閱，可直接合併。
