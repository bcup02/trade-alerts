# Perplexity 審閱歸檔 — 登記冊 sources 換到 A1 現行版（PR #158，f-27）

- **Repo**：bcup02/trade-alerts
- **PR**：#158，head `8f56c12444f0e217e0dc8db5820c5f0cbe37fedb`（兩個提交：`4a3797f`、`8f56c12`），base `fb9e2a4a3295d350a5ab37a5abcda4c925822a80`（main），squash 合併為 `f0dfc18`
- **審閱者**：Perplexity — 首審 **PASS**（一輪）
- **CI**：pytest = success（run `38034652855`；801 passed，baseline 801，沒有新增測試；審閱者註明 Actions 實際測的是 PR 與 main 的測試合併提交 `e97288e`）。不需要部署、不發 tag

## 內容

登記冊 `sources` 換到 A1 現行 operations（動能 `490e241→ac378ed`、趨勢 `960792e→489bbcd`、加密 `aba9569→4d13631`、競賽 `0409a9f→70630a1`，唯讀 ssh 逐一確認）。第一次用 f-18 的新腳本比對（`--against HEAD~1`）：231 處引用，0 shifted、0 unpaired、3 changed；3 處我讀過新舊提交的實際內容，同行同文字、前後行相同（趨勢與動能 `google_ledger_provenance.py` 同函式重複文字、競賽 `runner.py:597` 在多行 lambda 內），加 `--accept-changed` 後 0 problem。

- 提交 1 只改一個行號：`latch.restart_only_clear / seykota`（未做）的理由引用 `safe_halt_resume.py:103`（登記冊所用提交 960792e 那行是不相干的 `if (`），改成 `:134`。f-18 回測 #113 時發現，#113 通過審閱後仍留在 main 上。拆成獨立提交是因為新腳本不允許旗標放行 shifted。
- A1 執行環境說明重查（唯讀，2026-10-10 台北）：資金費同步動能四檔、趨勢三檔 blob 都沒變；競賽 `google_ledger_provenance.py` 因 f-26b 的分頁名稱常數 blob 變 `d0a5bb2`（引用三處文字不變）；A1 競賽 venv 共用庫 0.28.0→0.29.1（ledger_integrity `d11ef39`）。2026-10-08 部署時的紀錄與 2026-10-10 重查分開寫。
- 加密 `ops_notify.units_axis` 與 `FLEET.OPS_UNIT_FAILED`：使用者 2026-10-10 選「照現狀」：只盯資金費同步，換 Binance（x3）時補齊；仍是未做，階段改 `x3-crypto-binance`。
- `recent_changes` 7 筆（全是 updated）；兩張登記冊頁面重新產生。

## 審閱結論重點

- 審閱者獨立重算 231 個配對、0 unpaired；3 處 changed 對照策略倉庫不可變舊新檔案成立（競賽 `runner.py` 新舊整份 blob 相同 `4278c035`）；`:134` 在 960792e 與 489bbcd 都是拒絕解除的那段（`safe_halt_resume.py` 新舊 blob 相同 `13273b90`）。
- A1 blob、版本與 tag v0.29.1 的模組 blob 都與附件一致；2026-10-08 部署與 2026-10-10 重查分開，沒有把新版本冒充舊部署。
- 加密兩格維持 pending、`x3-crypto-binance` 存在；recent_changes 與實際七處修改一致；兩張產生頁與 JSON 一致（CI 的 render check 通過）。
- 非阻擋文字建議：`google.spot_fill_row` 沿用 10/8 的「等待 2026-10-09 每日調整」限制，建議日後補上「截至 2026-10-08」以免 10/10 之後被讀成未來事件。**未改**，等下一次改這格（e-2 第一次真的有競賽成交時）一併處理。

## 審閱者標明的界限

- 審閱者沒有連線 A1；`/opt` 實際檔案、venv 安裝版本、timer 啟用狀態屬附件中我的唯讀量測紀錄，審閱者只獨立證實 GitHub commit／tag 的檔案雜湊與附件一致。
- 沒有在本機 clone 重跑整支 `verify_registry_evidence.py`（獨立重算了引用配對數並核對 3 處原始碼）。
- PASS 不是部署授權。

## 教訓

- 新的比對腳本（f-18）第一次實戰就同時證明了價值與代價：抓到 #113 通過審閱後仍留在 main 的真錯引用；代價是同函式重複文字與 lambda 內的行會要人工比對（這次 3 處，約 10 分鐘讀完）。
- 「改正本來就錯的引用」要拆成獨立提交先改，再換 sources，否則會被判 shifted。
- 附件（腳本輸出＋3 處 changed 的新舊實際內容＋A1 量測）一次備齊，審閱一輪就過。

## 隔離聲明

只動 `src/trade_alerts/catalog/fleet-rollout-registry.json` 與兩張由它產生的頁面；沒有程式、錯誤清單、共用庫或部署變動。我的 A1 動作全是唯讀（`git rev-parse`、`git hash-object`、`ls`、`pip list`）。審閱者只讀 GitHub。
