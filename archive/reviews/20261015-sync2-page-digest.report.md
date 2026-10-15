# 登記冊頁面版本碼，重發前比對而不是讀整份頁面（phase-sync2） 審閱歸檔

- PR：bcup02/trade-alerts#195
- head：2fbebd94e8e1d656f1eec8f6251256c3a9e9f338（首審 dc7bab1a94e464555c9030b95e41e8fe722bae5e）／ base：ee7f4c627d742f0660ead22aabb99809993b39ce ／ squash：756c278d92a5c3759113803775d2cc66766865d6
- 審閱：ChatGPT，2 輪（第 1 輪 BLOCK，第 2 輪 PASS；審閱PR#195結論：PASS）
- CI run：38676972231（988 passed；首審 38675876062 為 984，baseline 981＋3＋4）
- 重點：兩張產生頁第 2 行註解與頁尾帶「頁面版本碼」（頁面 sha256 前 16 位；只把這兩處設成 16 個 0 再雜湊）；render_guides.py --check-published risk|rollout <存檔>：CURRENT 不用重發／STALE 直接發布新頁面／ALTERED 先讀再覆蓋；名詞對照表新增「頁面版本碼」（「指紋」是退休詞）；收尾 SOP 重發流程改寫；登記冊 google.spot_fill_row 競賽格限制句更正（append_fill_v2 首次實際送出 2026-10-15 台北 08:15）。
- 首審 BLOCK（兩點，皆可重現的 altered→current 誤判）：①只改頁尾版本碼不會被發現（頁尾碼被遮掉，比對只看註解碼）；②正文插入佔位字串會從雜湊輸入消失（全頁 replace）。修正：verify_digest 要求兩處各恰好一個且相同、只定點設零、其餘原樣雜湊；_page 檢查頁尾佔位字串恰好一個。補 4 個回歸測試。
- 審閱接受的取捨：雜湊涵蓋 <title> 到最後一個 </script>，平台外殼不在內，不是整份 HTML 的完整性驗證；版本碼不是簽章，攻擊者自行重算可繞過（防疏忽不防惡意）。
- 隔離聲明：審閱端未接觸實機；PASS 不授權部署。
