# PR #286 觀察區通知：台北時間＋ERR 編號＋Telegram 核對說明

- PR：bcup02/trade-alerts #286；head e8ccb550890d255ab31c746c51c51cab2cbfa873；base fac762320350d3fc8b0e1e774e2c54a389febf13；squash 2e4b47a4ec9d2559aa2631a79c8129c9d44b0667
- 審閱：ChatGPT 1 輪，結論 PASS（審閱PR#286結論：PASS）；CI run 39931740391，1480 passed
- 重點：持續提醒通知標 ERR-043～049、寫明 Telegram 要找的標題與次數、時間一律台北；「第 N 次」時間改用排程推算（狀態檔 last_at 只是最後取樣，使用者實測 16:10 ERR-048 為第 12 次）。
- 審閱者註明的界線：沒有獨立讀 ops-notify 的 slots_passed 實作（我方已對照 reminders.py 公式）。
- 部署：只需裝 scripts/observation_watch.py 到開發機（A1-dev），已於台北 10/23 17:30 前後安裝（sha256 66d8c6e3…）。
- 隔離：審閱端未接觸主機、交易所、帳本。
- 教訓：開發機（A1-dev）上的各 repo 副本沒有 GitHub 憑證，不會自己更新；登記冊 sources 換版後，phase-sync4 會因副本缺提交而「檢查壞了」，要用 git bundle 補提交。
