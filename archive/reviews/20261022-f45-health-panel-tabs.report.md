# PR #275 審閱歸檔：維運讀數面板加主機分頁（f-45）

- PR：bcup02/trade-alerts #275
- base：300eb5077150b6c7cf5470c709533bd47863b169；head：a04e22276ee828d524d414995464611ac9a075f5
- squash：見本檔對應 patch 的來源 commit（main 上「feat(register): 維運讀數面板加主機分頁…」）
- 審閱：ChatGPT 1 輪，PASS
- CI：run 39805237976，pytest 1471 passed，`*_node_test.js` 全過（第一次 CI 因既有頁面測試的時間競態失敗，已修）

## 重點
- 面板每台主機一個分頁：預設 A1 正式機（新），點「開發機」切換；一次只顯示一台，各自讀取與更新；role／aria／鍵盤（← → 循環、Home／End）。
- `fleet-health-sources.json` 新增開發機來源（帶真實 file_id）；A1 的 file_id 仍是 null。
- 不改版本號、不動共用庫程式、不動解析與過期判斷、不動連接器權限宣告（仍只有 Google Drive 的 read_file_content）。
- 審閱者提醒（非阻擋）：A1 預設分頁目前顯示「還沒設定讀數來源」屬預期；兩台都設定後不隨分頁停止 watch，讀取次數增加，維持既有節流；file_id 在 public repo 不是憑證，Google Drive 存取控制才是防線，已發布頁面不可公開分享。

## 隔離聲明
審閱者唯讀 GitHub 來源，未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或實機 state／ledger。
