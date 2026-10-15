# observation-watch 單元檔允許 git fetch 寫 clone 的 .git 審閱歸檔

- PR：bcup02/trade-alerts#202
- head：61d7e63e4de3b306cc22f1869c1cf8083a0f32c3 ／ base：57d9dba0ef21659b9ff8b0bd251b81aabaee8cc7 ／ squash：496eab82b26b13822795f7f3d5fe00af7bd5187d
- 審閱：ChatGPT，1 輪 PASS（審閱PR#202結論：PASS）
- CI run：38686501262（1046 passed）
- 重點：單元檔 ProtectHome=read-only 讓 git fetch 寫不進 .git/FETCH_HEAD，phase-sync1／4 檢查連續報壞；加 ReadWritePaths 只開登記冊 clone 與四支策略 clone 的 .git（缺的跳過）；新增守門測試。開發機合併前已用該分支重裝並驗證。
- 審閱接受的邊界：測試只驗必要路徑存在，不禁止未來更寬的寫入路徑；未做 mutation test；開發機驗證為開發端證據。
- 隔離聲明：審閱端未接觸實機；PASS 不授權部署。
