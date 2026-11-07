# PR #339 審閱歸檔：註冊事件專案 trend-meteor（前綴 MET，v0.30.24）

- PR：bcup02/trade-alerts #339；squash `364c1d8`；tag `v0.30.24`（打在 squash commit）；審閱 AI：ChatGPT；結論：BLOCK 一輪後第二次 PASS（head `8f6c5b55`，CI run 42397832919，1586 passed）
- 範圍：`PROJECT_CODE_PREFIXES` 加 `trend-meteor`／`MET`；錯誤清單 `projects`；三份 schema 專案列舉；ops 匯出與錯誤清單 schema 的代碼規則；`REGISTRY_PENDING_PROJECTS`（登記冊欄位、`sources`、`MET.*` 條目留到 V11 登記冊工作）與 `registry_problems` 守門；版本 0.30.24。
- 為什麼：流星池（趨勢策略・流星池版 V11）以專案名稱 `trend-meteor` 寫事件，但清單沒有它，`append_fleet_event` 丟 `FleetEventLogError` 被策略端吞掉——5c-1 以來所有流星池事件都沒寫進日誌（未部署，沒有實際損失）。

## 審閱歷程
| 輪 | head | 結論 | 內容 |
|---|---|---|---|
| 1 | `702fe35` | BLOCK | 339-01：`fleet-ops-export-v2` 的 `project` 列舉加了 `trend-meteor`，但 `notices[].code`／`open_requests[].code` 的正規表示式仍是 `^(SEY|MOM|MYC|BTC|FLEET)\.…`，合法流星池事件產生的 ops 匯出通不過自己發布的 schema；新增的 schema 測試只掃 `project.enum`，CI 綠燈是測試覆蓋不足 |
| 2 | `8f6c5b5` | PASS | 兩處補 `MET`；同類漏洞（`fleet-error-catalog-v2` 兩處）一併補；新增端到端 ops 匯出測試（真的產生 MET 通知與請求並用 schema 驗證整份文件）與通用守門測試（所有含 `SEY` 的 pattern 必須接受每個已註冊前綴） |

## 刻意不做（審閱者確認取捨合理）
`fleet-rollout-registry-v1.schema.json:242` 不加 MET：流星池尚無登記冊欄位，由 `registry_problems` 的 pending 守門擋住 MET 目錄條目；V11 登記冊工作建立 MET 條目時必須同步更新 registry schema、`sources`、35 項能力欄位與 `REGISTRY_PENDING_PROJECTS`。`observation_watch.py` 的專案清單等 5d。消費端（ops-notify）若用舊 schema 嚴格驗證需另行升級；策略端改釘另開 PR。

## 教訓
1. 新增一個「列舉型」的值（專案）時，要把**所有**出現列舉的地方一次找全（程式表、JSON schema 的 enum、各 schema 的代碼正規表示式、測試對照表），並寫一個通用守門測試掃出漏網處，不要靠逐處記得。
2. schema 測試要驗證「用真實產生器產出的完整文件」能通過，而不是只驗證列舉裡有這個值。
3. 共用庫的列舉缺漏會讓策略端的事件記錄靜默失敗（被『事後紀錄不能讓交易停』的設計吞掉）：新專案接上共用庫時，第一件事要用真實共用庫寫一則事件並讀回，不能只用假事件測試。
