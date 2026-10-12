# f-40 register-page-jump 審閱歸檔

- PR：bcup02/trade-alerts#177
- head：8c0741d ／ base：7615341 ／ squash：ba383ac2a8c1e2f427930a041153baee23a67e3a
- 審閱：ChatGPT，1 輪 PASS（審閱PR#177結論：PASS）
- CI run：38220115996（884 passed（baseline 870，+14））
- 重點：風險登記冊頁面新增錯誤編號下拉選單（選了就捲到區塊、展開步驟、標示、寫入網址 #ERR-xxx；篩選藏起來時先清掉；網址帶 #ERR-xxx 載入即跳）與每個區塊的 R0–R3 標籤；tests/test_risk_register_page.py 用 QuickJS＋DOM 替身實際執行頁面腳本（14 個測試）；v0.30.5。
- 審閱留下的非阻擋限制：清篩選依賴每組第一個按鈕是『全部』；row.className.indexOf('row') 非嚴格 class 比對；測試未覆蓋『只看還沒做完』後再跳轉與真實瀏覽器視覺（已在 Chrome 實測 ERR-044）；pytest.importorskip(quickjs) 缺依賴時會跳過。
- 隔離聲明：未改交易、下單、停損、帳本寫入邏輯；PASS 不等於部署授權。
