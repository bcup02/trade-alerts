# 已做格子拆欄位 verified_at／limit（phase-sync4b） 審閱歸檔

- PR：bcup02/trade-alerts#200
- head：4038b55bb6c4ede6652884889f0fc48d36a4d9a7（首審 aa94ec06a987a9a282f5578b16d2cb673b059fa3；PASS 後因 #199 先合併，SOP 一行衝突，保留雙方後 rebase，程式與資料內容不變）／ base：8c4c61a4bf5050b4435f6859e48eefef36d3b450 ／ squash：a90b1aba225dbade88ae78014ea137db4764689f
- 審閱：ChatGPT，2 輪（第 1 輪 BLOCK，第 2 輪 PASS；審閱PR#200結論：PASS）
- CI run：38685062394（1034 passed；首審 1033）；rebase 後 run 38686153460 綠燈、本機 1031 passed
- 重點：86 個已做格子的長散文拆成 evidence（程式做了什麼＋檔案:行號，≤700 字）、limit（≤300 字）、verified_at；A1 唯讀查證長文移到 docs/registry-a1-checks.json（60 格）；未做／不適用 reason ≤450 字；頁面分開顯示限制與查證日期；CI 擋超長與放錯格子。
- 審閱 BLOCK：遷移取段落第一個日期當 verified_at，其中 14 格取到的是部署日期。修正：只有「執行環境（…唯讀查…）」括號內帶日期才填，其餘省略；14 格刪除、46 格保留；日期加日曆有效性檢查；新增逐格對照測試。
- 審閱接受的邊界：verified_at 是歷史查證標記不是即時監控；測試只證明資料符合擷取規則，不是獨立證明當年查證發生過；存檔長文不再被 verify_registry_evidence／registry-drift 涵蓋。
- 還沒做：兩張登記冊重發（頁面版本碼會是 STALE）。
- 隔離聲明：審閱端未接觸實機；PASS 不授權部署。
