# 維運讀數試算表與 Apps Script 專案：建置清單（f-45）

給**使用者**照著做的清單。做完之後，A1 正式機（新）與開發機的發布單元才有地方送讀數、一致性登記冊最上方的「維運讀數」面板才有地方讀。
**這份清單的 A 段完全不碰 A1 與開發機**，可以現在就做；B 段（主機上）要等 x7 觀察期滿（約 10/26）並由我先問你再做。

## 先搞清楚為什麼要「獨立」的試算表

- 讀數表是**一個儲存格**（`HEALTHv1|…|HEALTHEND`，約 500 字元）。登記冊面板用你的 Google Drive 連接器讀整份試算表的文字，連接器對大檔案可能回不完整、同一份試算表有多個大儲存格時每格會被截斷（2026-10-20 實測）。所以讀數**不放進**「AI自動程式交易紀錄」，另用只有一個分頁、一個儲存格的小試算表。
- 接收端 `.gs` 是綁在試算表上的，所以每份小試算表要有自己的 Apps Script 專案，貼同一份 `apps_script/google_ledger_receiver.gs`、只登記一個來源。好處：健康密鑰不用登記在帳本接收端、帳本接收端不用重新部署、這個專案裡根本沒有帳本分頁可碰。
- 兩份：**A1 正式機（新）**一份、**開發機**一份（開發機要先驗證整條路；兩台寫同一格會互相覆蓋）。登記冊面板目前只讀 A1 那份。

## A 段：建試算表與專案（現在可以做，不碰任何主機）

**前置：用哪個 Google 帳號？** 用**接到 claude.ai 的 Google Drive 連接器的那個帳號**建（這樣面板不用另外分享就讀得到）。瀏覽器同時登入多個帳號時 Apps Script 會開錯帳號，請用只登入該帳號的無痕視窗。

對 **A1 正式機（新）**與**開發機**各做一次（先做開發機）：

1. 建一份新的 Google 試算表，命名：`維運讀數（A1 正式機）`／`維運讀數（開發機）`。
2. 把預設分頁改名為 **`維運健康`**（一字不差），**刪掉其他分頁**，A1 留空。這份試算表裡不要放任何別的東西。
3. 試算表網址 `https://docs.google.com/spreadsheets/d/<檔案編號>/edit` 中間那段就是**檔案編號**，記下來（面板設定要用；不是機密，但別貼到公開的地方）。
4. 在這份試算表：擴充功能 → Apps Script。把整份 `apps_script/google_ledger_receiver.gs`（trade-alerts main）貼進去，覆蓋預設內容，存檔。
5. 專案設定 → 指令碼屬性：
   - **不要**加 `SHARED_SECRET`（沒有它，舊協定的請求一律被拒絕，這正是我們要的）。
   - `GOOGLE_LEDGER_V2_SOURCES` **先不加**：密鑰要在主機上產生（B 段），產生時終端機會印出整行要貼的內容。
6. 部署 → 新增部署 → 類型「網頁應用程式」：
   - 執行身分：**我（你的帳號）**
   - 誰可以存取：**所有人**（發布單元沒有 Google 登入，靠簽章驗證；沒有登記來源前任何請求都回 `source_not_allowed`）
   - 第一次部署會要求授權（Review Permissions）：用同一個帳號同意。
   - 記下 **網頁應用程式網址**（`https://script.google.com/macros/s/…/exec`）。
7. 把兩份的**檔案編號**與**網頁應用程式網址**交給我（貼在對話裡即可）：網址會寫進該主機的 `health-publish.env`（`HEALTH_PUBLISH_URL`），檔案編號會填進 `fleet-health-sources.json`。網址不是金鑰，但知道它的人能對它送請求（會被簽章擋下），請別公開貼。

做完 A 段，我會先**不靠主機**驗證兩件事（只用我這邊的 Google Drive 工具，唯讀）：
- 把一個我產生的測試儲存格手貼進 `維運健康` A1，用連接器讀回來，確認格式完整、沒被截斷或跳脫成我們解析不了的樣子；
- 對網頁應用程式網址送一個**假簽章**的探測請求，確認回的是 `source_not_allowed` 而不是 403 或「Authorization needed」（執行身分沒授權的徵兆，見 2026-10-08 的教訓）。

## B 段：主機上（等 x7 觀察期滿，我會先問你；先開發機、再 A1）

每台主機（先 A1-dev，開發機，再 A1 正式機（新））：

1. 部署該主機 ops-notify 的新版（照一般部署流程）；環境檔 `/etc/ops-notify/health-publish.env` 從範例建立，填 `HEALTH_PUBLISH_URL`（該主機那份的網址）、`HEALTH_PUBLISH_SOURCE_ID`（`fleet-health-dev`／`fleet-health-a1`），先維持 `HEALTH_PUBLISH=off`。
2. 在主機上執行 `sudo bash /opt/ops-notify/deploy/configure_health_publish_secret.sh <來源 id>`：密鑰**在主機上產生**、只在終端機顯示一次（附要貼進 Apps Script 的那一整行）。**立刻**把那一行貼進該專案的指令碼屬性 `GOOGLE_LEDGER_V2_SOURCES`（鍵是來源 id；`allowed_actions` 必須剛好是 `["put_health_v1"]`）。
3. 把 `health-publish.env` 改成 `HEALTH_PUBLISH=on`，重新執行 `install.sh`（它只在旗標為 on 且密鑰檔存在時才啟動 timer，並回讀確認）；手動跑一次 `ops-notify publish-health --dry-run`，再看第一輪真的送出。
4. 確認 `維運健康` A1 有內容，再填 `fleet-health-sources.json` 的 `file_id`、重新產生並重發一致性登記冊。

## 之後才做（登記冊重發）

- 重發登記冊要帶 `capabilities`（`render_guides.HEALTH_CAPABILITIES`：只有 Google Drive 的 `read_file_content`），**用到連接器的頁面不能公開分享**；第一次開頁面會問你是否允許頁面使用 Google Drive 連接器。
- 面板顯示規則（過期 25／45 分鐘、時鐘不一致、無讀取時間）見 `scripts/health_panel_core.js` 與 `docs/guides/README.md`。

## 常見問題

- **請求回 403／「需要 Drive 存取權」**：先懷疑 Web App 的執行身分沒授權：用該帳號打開網頁應用程式網址、按 Review Permissions 同意（不是換人重部署）。
- **`signature_invalid`**：兩邊的密鑰不一樣（主機上重新產生過、或貼錯），或主機時鐘飄移。重新產生要用 `--rotate`，並立刻更新指令碼屬性。
- **`health_sheet_not_allowed`／`sheet_not_found`**：分頁名不是 `維運健康`、或來源登記的 `sheet_name` 不對。
- **`action_not_allowed`**：來源登記沒有 `allowed_actions`，或不是剛好 `["put_health_v1"]`。
