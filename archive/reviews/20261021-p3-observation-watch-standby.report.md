# 審閱歸檔：observation-watch 新主機預檢與安裝步驟（PR #256，階段 3 P3）

- PR：bcup02/trade-alerts #256；squash `579ebfe2c0e0ae62e451958b552b8f7c6f39f839`
- 最終 head `da3e41d0849fe37025cb1235059795fe0a6b3a07`；base `70c8a7f4afab1686665c7b14fab19ed4c7391cbd`
- 審閱：2 輪（ChatGPT）。首審 BLOCK（head e77a25b）→ 複審 PASS（head da3e41d）。CI：run 39406325676（1201 passed）→ run 39414239201（1205 passed）。

## 重點
- 盤點：`install.sh` 與單元本來就用 `WATCH_USER`／`@WATCH_USER@` 參數化，新機用 `WATCH_USER=ubuntu` 即可，不改程式與單元。
- 新增 `watch_preflight.sh`（警告式預檢：5 個 clone、A1 在 known_hosts、金鑰權限；不印祕密），`install.sh` 開頭呼叫；`docs/observation-watch.md` 加「裝在新主機」6 步。

## 首審 BLOCK 與修正
- BLOCK-256-01：金鑰權限的 `stat` 失敗在 `install.sh` 的 `set -e` 下會中止安裝，違反「預檢只警告」→ `stat` 放進 `if` 條件並驗證輸出為八進位，失敗轉成警告；測試改在 `set -euo pipefail` 下跑並印 `INSTALL_CONTINUES`，新增 stat 失敗／亂碼／空輸出三個注入測試。

## 限制
- 合併不等於部署；未部署開發機、A1 或 standby。切換日 P3 用手冊的手動步驟（trade-alerts main 的 `install.sh` 即可，含此預檢）。
- 審閱端未做本地 checkout 與 mutation test；`.gitignore` 白名單規則未逐條核驗（新檔已以 `git add -f` 加入）。

## 隔離聲明
開發端測試用暫存目錄與 stub；實機只在空機 fleet-standby-2 試裝後 disable；未碰開發機、standby-1 或 A1。
