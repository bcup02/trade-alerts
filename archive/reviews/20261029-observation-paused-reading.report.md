# PR #325 觀察區 a1-stable 認得運行狀態 PAUSED（f-78）

- PR：bcup02/trade-alerts #325；base 332ea4e1ed8230aec4b2b76050bbdc09af66b5f1；squash d9764846624fc418bb59c8a8647c98b70051b378（不打 tag，沒改版本號）
- 審閱：ChatGPT 2 輪。首審 head 5a720f425c73ea6f3d2dff43a59df01c969d2337 **BLOCK**（BLOCK-325-01）；複審 head b4d69ef619a158fadf281f3228ad49f88d0fc2af **PASS**（審閱PR#325結論：PASS）。CI run 40825891371／40830351127，1574／1576 passed（baseline 1570）。
- 重點：runtime 軸 PAUSED 且 severity ok 不重算穩定時間，但不算穩定證據；摘要在有暫停策略時改為「運行中的策略與主機（不含暫停中的 X）…暫停中的 X 沒有被驗證，結案只對運行中的策略有效」。
- **BLOCK 與教訓：** 邏輯正確但摘要與 `closable` 仍寫「四支策略連續正常」，細節證據只放在 evidence 裡，看摘要的人會被誤導。教訓：放寬一個條件時，結論文字（summary）與結案語意也要同步限定範圍，並用測試直接斷言 summary，不只驗證 evidence。
- 審閱者決定：`closable=True` 可接受，因為 x8、f-63、x5 不依賴趨勢策略，但不得延伸到專門要求趨勢運行的觀察項目。非阻擋備註：未滿 72 小時的摘要措辭與原文不完全相同（更明確）；「每一輪偵測都看到全部正常」那行 evidence 可再收斂。
- 部署：只換單檔到開發機（`/opt/observation-watch/observation_watch.py`，備份 `~/observation_watch.py.bak-20261029-paused`，2026-10-29 台北 14:47）。
- 隔離：審閱端未接觸主機、交易所、帳本。
