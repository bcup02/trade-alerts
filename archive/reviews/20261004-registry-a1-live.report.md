# 登記冊：A1 正式機（新）上線後的改格

- PR：[bcup02/trade-alerts#113](https://github.com/bcup02/trade-alerts/pull/113)，squash 合併 `2de686f`（base `19f3ea9`）
- Perplexity：首審 **BLOCK**（head `b28613b`）→ 修正後複審 **PASS**（head `bdd6a3a`）
- CI：pytest 456 passed（run 37201556023）

## 內容

2026-10-04 搬家階段 C 完成後，A1 正式機（新）跑 operations 版本（動能 `ce51083`、趨勢 `ed50b1d`、加密 `b5a605f`、競賽 `ac99132`）。登記冊 12 格改已做：`stop.graceful`（四支）、`recovery.interrupted_order`（四支）、`repair_bot.recurrence_escalation`（動能、趨勢）、`SEY.PROTECTION_MOVE_DEFERRED` 趨勢 emits_event；同一規則的行為說明改寫成 f-14 的每 10 分鐘自動重試。`sources` 四個提交改到 A1 在跑的版本。`notify.error_id` 四格維持待辦（兩則格式還沒在正式機實際送到手機）。

## 審閱

首審 BLOCK 兩項：
1. **換版後既有引用失配**：換了四個 `sources` 提交，卻沒有檢查既有格子，108 處 file:line 指到別的程式（例：動能 `repair_bot.py:95` 空白）。`verify_registry_evidence.py` 只查行存在，所以仍顯示 0 problem。修正：把所有沒改過文字的 done 格子的引用，逐筆重新定位到新提交上「同一行文字」（檢查 134 處、行號有變動 108 處、4 處手動對應），並比對舊提交那行文字＝新提交新行號那行文字。
2. **recurrence 兩格缺 A1 執行環境綁定**：補 A1 修復機器人 unit 的 ExecStart、venv 內 trade-alerts 0.26.0 的模組路徑與檔案 blob（與 tag v0.26.0／v0.25.0 同檔相同）、執行時讀回的門檻常數、15 分鐘排程與最近一輪日誌、adapter 呼叫行。

複審另外接受：趨勢移動停損延後那格（開發端自己發現說明還寫「下一根 K 棒再試」，實際已是 f-14 每 10 分鐘重試）的改寫與 emits_event 改已做。

審閱者非阻擋註記：附件摘要的引用筆數（137／134／9 筆 DIFF）前後不一致，實際為 125 OK、8 DIFF、1 COUNT MISMATCH（那一格已改寫）；PR 主內文原本還是初版 10 列摘要，已同步成 12 列。

## 教訓（重複犯錯）

2026-09-26 的歸檔 `20260926-g1-5-registry.report.md` 已寫過「重對行號後要用程式內容比對驗證」，這次換 sources 時我沒有先讀它，重犯同一類問題。以後任何 `sources` 換版：先跑「舊提交行文字＝新提交行文字」的逐筆比對，再送審；`verify_registry_evidence.py` 本身抓不到。把這個比對做成腳本功能，另開 PR。

## 隔離聲明

本 PR 只動 `src/trade_alerts/catalog/fleet-rollout-registry.json` 與兩張由它產生的頁面；沒有程式碼、deploy、tests 變動，不需部署。審閱者只讀 GitHub 與附件，沒有接觸實機。開發端在 A1 的動作都是唯讀（`git hash-object`、`pip show`、`systemctl cat`、`list-timers`、`journalctl`）。
