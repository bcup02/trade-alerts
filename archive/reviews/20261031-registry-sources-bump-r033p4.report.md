# PR #327 登記冊：競賽 sources 換到 A1 現行版 831bb96（R033 P4 部署）

- PR：bcup02/trade-alerts #327；base 5b46e28b7d660d37c8ab01ec2e7e3e202b9ef461；squash 5ea2171（CI run 41180780965，1576 passed）
- 審閱：ChatGPT 1 輪，head 8b3e5e46a002bd6de9bad04980f75172ac98720a PASS（審閱PR#327結論：PASS）。
- 重點：競賽 sources 9a6b0c9→831bb96。腳本自動搬移 shifted 引用；6 筆 changed 逐筆人工讀過接受（interrupted_orders.py:181→:159 兩格、:84→:101；reconcile_compare.py:219→:255；runner.py:914→:1122、:630→:695）。兩格 limit 改寫（recovery.interrupted_order、reconcile.unrecorded_fill_handling）；bear.paxg_asset 維持 pending（A1 開關未打開）；ERR-070 sources :768→:591、ERR-071 :766→:577。
- 審閱者備註（非阻擋）：PR 內文測試數字（1562）與 CI 原始日誌（1576）不符，已在合併前更正；審閱端未重跑 verify_registry_evidence.py 與 render_guides.py --check（無法建立本地 checkout），改以兩個 commit 的原始檔逐筆驗證。
- 教訓：簡寫行號與 limit 文字腳本都不比對，手動改後仍要逐一核對；ERR-070／071 的 sources 在上一輪建立時就已與 operations 版不符，換版時要連錯誤清單的 sources 一起查。
- 部署：不用部署（資料）。競賽策略 831bb96 已於 2026-10-31 台北 16:23 部署 A1（共用庫 0.30.23），開關 BTC_COMP_PAXG 未打開。
- 隔離：審閱端未接觸主機、交易所、帳本；未動任何 .py。
- 歸檔註記：patch 不含 docs/guides 的產生頁面。
