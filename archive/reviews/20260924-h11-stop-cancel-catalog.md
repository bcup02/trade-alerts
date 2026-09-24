# Perplexity 審閱歸檔 — docs: SEY.PROTECTION_MOVE_DEFERRED; retire the unreachable SEY.PROTECTION_ORPHAN_CANCEL_FAILED (h11)

- **Repo**：bcup02/trade-alerts
- **PR**：#65，首審 head `0ea3e31295896a3bff663a74f181210c569bcd0d`（BLOCK）→ 複審 head `54c43ccc9ed7af10d4f114f8380ef4478504bc71`（PASS），base `main` @ `8a31b47`，squash 合併為 `21264c3`
- **審閱者**：Perplexity — **`BLOCK` → `PASS`**
- **CI**：pytest = success（run `36017038332`；363 passed）
- **對應待辦**：機隊工程進度 `phase-h11`；程式配套 AI-for-column/ed-seykota-systematic-trend-following #74（821c91f）
- **發版**：不發版，資料隨下一版 trade-alerts 一起出去（比照 #56）

## 做了什麼

依 Binance 測試網 2026-09-24 實測（h5：同方向第二張 closePosition 停損 -4130；h11：掛單清單無延遲、重複撤單 -2011、平倉後停損自行消失）：
新增 `SEY.PROTECTION_MOVE_DEFERRED`（R2）；`SEY.PROTECTION_REPLACE_FAILED` 標題與說明改為「部位可能沒有交易所端保護」，涵蓋撤單結果不明；
`SEY.PROTECTION_ORPHAN_CANCEL_FAILED` 列入 retired_codes（entry 保留到 #74 上正式機）；登記冊新增 phase `hotfix-seykota-stop-resolution` 與兩列 pending；兩張頁面重新產生。

## 審閱經過

- **首審 BLOCK**：新條目 `operator_message.direction` 寫「連續 3 次都移不動才通知你」，但 #74 每次延後都呼叫 `_notify(critical=True)`（其自身測試第一次就斷言通知），文字把第 8 關的目標設計寫成現行行為。其餘五項（退役理由、標題變更影響、範圍、登記冊算術、回歸）PASS。
- **修正**：開發端核對時另發現審閱者建議的「每次都立即通知你」也不正確——ed-seykota 的 `_notify` 目前只寫主機日誌、不推播（第 8 關才接上共用事件日誌）。`direction` 與 `auto_action` 改為照實寫：現在每次只記一筆緊急紀錄、不會送到手機；「連續 3 次才通知」標為第 8 關規劃。
- **複審 PASS**：差異只有兩個欄位與對應渲染文字；審閱者以程式碼搜尋獨立查證 `_notify` docstring 與 CLAUDE.md 的 log-only 記載屬實；HTML 與 JSON 逐字相同。

## 教訓

寫給人看的行為描述（尤其「會不會通知你」）前，先查清楚那條通知管道現在是否真的會送出，不要沿用鄰近條目的目標設計措辭。

## 隔離聲明

只動錯誤目錄／一致性登記冊 JSON、人讀文件與產生的頁面；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或正式機帳本。完整差異見同名 `.patch`（src 與 docs/fleet-error-catalog.md；docs/guides 兩頁為 render_guides.py 產物，未收入）。
