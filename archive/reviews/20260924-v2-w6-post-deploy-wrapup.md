# Perplexity 審閱歸檔 — docs: v2-W6 post-deploy wrap-up — registry done cells, catalog sources, retire PROPOSED

- **Repo**：bcup02/trade-alerts
- **PR**：#52，最終 head `d2b69569e6777a2fb85c5710e81b040fd866a856`
- **base**：`main` @ `f404ee9`
- **squash 合併為**：`babd91b`
- **審閱者**：Perplexity — 首審 **`BLOCK`**（head `408e00b`）→ 複審 **`PASS`**
- **CI**：pytest = success（首審 run `35910580983`、複審 run `35910970080`；342 passed）
- **對應待辦**：機隊工程進度 `phase-v2-w6`（分級 v2 部署後收尾）；同批 bcup02/ops-notify#22（設定範例，純文件）
- **部署**：不需要；合併後重新產生並重新發布兩張登記冊頁面。錯誤目錄變更隨下一版 trade-alerts 發布。

## 做了什麼

W6 於 2026-09-24 上正式機（momentum operations 3a91dd0、seykota operations f9946ba）並打開轉送開關後，讓登記冊反映現況：
sources 換到兩個新 operations commit；修復機器人三功能、匯出檔、轉送開關、服務單元監控、動能策略的 LINE 首則通知、
趨勢策略的「市價單只送一次」、6 條 runner 代碼規則列改 done；趨勢策略 bot.py 因 #65 位移而失準的 8 條既有引用重新對齊；
MOM./SEY.VERIFIED_CLOSE_PROPOSED 從目錄與登記冊移除（retired_codes 保留）；SEY.POSITION_AMBIGUOUS 補上 #65 呼叫點與追查指令；
3 個寫死部署前狀態的測試改寫（未改弱）。

## BLOCK 與修正

1. `notify.line_first_notice`／seykota 原標 done，證據是「與動能策略共用同一條 ops-notify→LINE 路徑」。審閱者指出：共用拓撲不等於
   趨勢策略的匯出通知已被選中、渲染、送出且只送一次。改回 pending（phase v2-W6），完成條件寫明「趨勢策略專屬受控測試：sent=1、
   手機收到、下一輪不重送」。
2. 審閱者的 GitHub 連接器讀不到指定 operations commit 的檔案內容（同 #50 首審），無法逐格核對新 done。以程式從登記冊 diff 取出
   每一格新 done 的每個引用，用 `git show <operations sha>:<path>` 取原文＋前後文＋固定連結貼成 PR 留言（含 `:NN` 簡寫行與
   兩支 operations 上 `git grep VERIFIED_CLOSE_PROPOSED` 皆無結果），複審據此逐條核對後 PASS。

教訓：證據檢查器只抓「行號超出檔尾」，抓不到「行號還在但內容變了」——策略程式有增刪行的部署後，登記冊引用要逐條看內容。
審閱者讀不到原始碼時，直接附上原文摘錄比把格子保守改回 pending 更好（格子本身是對的）。

## 刻意不做

趨勢策略 `tests/test_rollout_registry_self_check.py` 的 `RENAMED_AHEAD_OF_DEPLOY` 豁免：該測試讀已安裝套件（v0.21.0）裡的登記冊，
要等策略改釘到含這份登記冊的版本才過期，已排進 v0.22.0 改釘選（通知計畫 WP3）。

## 隔離聲明

只動登記冊 JSON、錯誤目錄 JSON、兩個 render 產生的 HTML、3 個測試檔；無程式碼、部署或秘密變更。完整差異見同名 `.patch`。
