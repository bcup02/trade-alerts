# 進度頁靜態外殼：連結檢查改讀資料庫匯出（phase-sync5） 審閱歸檔

- PR：bcup02/trade-alerts#206
- head：e00f13a7a20f7c732e3fff3b9aeeb5199d37ef9b（首審 0b99b671c9ad5fc1e33eb7e0faaab9a17c4e3df7）／ base：57c7c89ae854164c4e2971360c26cfa824cb7302 ／ squash：615a8c0ebaacd509169d03344ba7cbeb5fe9be7a
- 審閱：ChatGPT，5 輪（前 4 輪 BLOCK，第 5 輪 PASS；審閱PR#206結論：PASS）
- CI run：38703586878（1078 passed；首審 1059）
- 重點：進度頁改成靜態外殼（頁面 v236，資料全在頁面資料庫，逐項 set／update 帶 if_version）；scripts/check_progress_links.py 新增 --db-dir 讀資料庫匯出（checklist/<id>.json、meta/watch.json）；收尾 SOP 第 4 段改寫。
- 審閱 BLOCK 全是「讀不懂的輸入沒有受控報錯」：①用法錯誤 exit 2 與契約不符（改回傳 1）；②checklist 讀檔 OSError 逃出（轉 ValueError，--items-json／頁面讀檔同樣處理）；③登記冊讀取失敗（--registry 不存在／壞 JSON／origin/main 讀不到）逃出 try；④登記冊合法 JSON 但缺 capabilities／catalog 會靜默通過；⑤登記冊格子缺 state 丟 KeyError、done 沒 evidence 被當完成。修正：③全部納入受控處理；④⑤改成複用登記冊自己的 registry_problems 規則（CI 對登記冊跑的同一套），另對 link_problems 的 KeyError／TypeError／AttributeError 做深度防禦。教訓：新增輸入來源時，一開始就把「每一種讀不到／讀不懂／結構不全」列成一張表逐項處理，不要逐輪補；能複用既有驗證器就複用。
- 審閱接受的邊界：--registry 指定舊版登記冊若與目前錯誤清單不一致會被拒（fail-closed，可接受）；匯出混到舊目錄的舊檔無法識別（SOP 要求新的空目錄）；checklist 下非 *.json 檔被忽略；檢查仍是手動跑，CI 與觀察區讀不到平台資料庫；頁面打勾寫入發布後未實際點過。
- 隔離聲明：審閱端未接觸實機與平台資料庫；PASS 不授權部署。
