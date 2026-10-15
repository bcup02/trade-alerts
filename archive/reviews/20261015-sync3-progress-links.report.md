# 進度項目連到登記冊格子、互相檢查（phase-sync3） 審閱歸檔

- PR：bcup02/trade-alerts#197
- head：d70d3e60ab07a19ffd27c9182fd8ee754c263c32（首審 2189c70bf9a3e01090ce81386dbfbc6e1a341118）／ base：4e60a1c67d1c4ad7fd49bb679bc305e68057941c ／ squash：d5ac78b887bb5a20e72820d59ddecd426151e3cd
- 審閱：ChatGPT，4 輪（前 3 輪 BLOCK，第 4 輪 PASS；審閱PR#197結論：PASS）
- CI run：38682575378（1027 passed；首審 38678570071 為 1007，baseline 988＋19＋…）
- 重點：scripts/check_progress_links.py——進度項目帶 "registry": ["cap:<能力>@策略,策略", "rule:<代碼>#面向"]，對 origin/main 的登記冊檢查：項目 done 但格子未做、項目還開著但格子全做完（觀察區項目豁免）、連結指到不存在的能力／代碼／策略／面向、registry 值不是非空字串清單、status 不是已知值，皆報錯；收尾 SOP 補一行。
- 審閱 BLOCK 全是「靜默漏檢」類：①只讀單行 JSON 項目；②@策略,策略 只要一個有格子就通過；③拼錯 status 繞過；④帶 registry 的 JS literal 項目被略過；⑤"registry": null 被當成沒有欄位；⑥單引號 'registry': 被略過。修正：用 JSON 解碼讀單行／多行項目；指定的每個（策略、面向）都要有格子；status 必須是已知值；欄位存在就必須是非空字串清單；欄數比對改成 fail closed（任何寫法的 registry 鍵都要對得上讀到的項目數，否則報錯）。教訓：靜默通過類缺陷要一次把「讀不懂就報錯」做成通則，不要逐種寫法補。
- 審閱接受的邊界：計算屬性或 Unicode 跳脫的鍵、ITEMS 區塊之外的欄位屬不支援輸入；文字內出現 registry: 會 fail closed 誤報；_block 固定 \n  ]; 格式；解碼失敗後 position+1；origin/main 需先 git fetch。
- 還沒做：連結資料（合併後在進度頁加）；自動化（進度資料搬進 repo 後，phase-sync5）。
- 隔離聲明：審閱端未接觸實機；PASS 不授權部署。
