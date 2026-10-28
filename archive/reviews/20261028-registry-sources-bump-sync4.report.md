# PR #316 登記冊：sources 換到 A1 現行版（動能 fcbd71d、加密 097fe19），重驗行號

- PR：bcup02/trade-alerts #316；base 8a06c0354e7a3ce187de06e79a1cb2e2c3f42374；squash 1c63ea8815b86d9dbf227d9acb14f4ad091b610a
- 審閱：ChatGPT 2 輪。首審 head 53dff8aad2e6f5a8649daf6229b069cefca683c2 BLOCK（審閱PR#316結論：BLOCK）；複審 head ece901f098a25e75cea11118e59ec6f65782708b PASS（審閱PR#316結論：PASS）。CI run 40687505342，1570 passed。
- 重點：觀察區 phase-sync4（A1 部署後兩個被引用的檔案與 sources 提交不同，26 格）。sources 動能 ba822c2→fcbd71d、加密 c185c1d→097fe19；24 處 file:line 逐筆驗證舊行文字＝新行文字。
- BLOCK 原因與教訓：我的換行號腳本只認完整的「檔名:行號」，同一段裡的簡寫 :N（「repair_bot.py:369、:354」「:325、:309」「（:202 呼叫…）」）沒被更新，三處指向新版的錯行。以後換 sources：除了完整引用，還要掃每格 evidence／limit 的所有裸 :N 與逗號後的數字，逐一判斷屬於哪個檔案並驗證。
- 部署：不用部署（資料）；合併後重發一致性登記冊。
- 隔離：審閱端未接觸主機、交易所、帳本；未動任何 .py。
- 歸檔註記：patch 不含 docs/guides 的產生頁面。
