# PR #389 審閱歸檔：登記冊 sources 換到 A1 現行 operations commit（動能 c53f6d1、加密 93039e5、競賽 a78c775）

- PR：bcup02/trade-alerts #389；squash `fe7b494`；tag `v0.30.46`；審閱 AI：ChatGPT；結論：第 1 輪 PASS（head `2005ede`，base `fa24f92`，CI run 44278430958，1679 passed）。
- 範圍：三個 sources 換新；`verify_registry_evidence.py` 比對 422 筆引用（5 筆 shifted 用 --relocate 搬、3 筆 changed 因競賽 runner.py 新舊 blob 相同而接受）；釘版行號與 A1 共用庫版本現況句更正（歷史部署句保留）；recent_changes 兩筆 updated；頁面重產。
- 審閱者獨立重做比對：422 筆全部配對、零未解決、416 筆所指檔案未改、6 筆讀新舊內容逐行相等；runner.py blob `69dbb69a…` 相同；`projection_outbox.py` blob 在 v0.30.19 與 v0.30.44 皆 `583bc2e2…`；寬限預設 3600 秒兩版相同。
- 部署：一致性登記冊已重發（第 107 版）；三支 operations 新 commit 的 bundle 已送 A1-dev 偵測副本，phase-sync4 不是「檢查壞了」。

## 已知缺口與後續
1. 審閱者沒有連線 A1 重量 venv blob，A1 三支 blob 583bc2e 是我 2026-11-18 在 A1 量的。
2. 舊趨勢（seykota）格子與 sources 未動，留歷史。

## 教訓
1. 換 sources 時，除了舊新行比對，還要掃「現況句」（A1 venv 版本、釘版行號）；這次發現競賽的釘版句本來就寫錯（寫 v0.30.19，A1 實為 v0.30.23）、動能 pyproject.toml:70 本來就不是釘版行。
