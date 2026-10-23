# PR #288 ERR-043 處理步驟補競賽資金進出登記工具（f-68，v0.30.20）

- PR：bcup02/trade-alerts #288；首審 head aff9a3ad870fb29acef5dd3126b2225fdacfa9f4 → 複審 head 7942b11579fb70b22cb3a8b571cb8a493bd4f275；base 31b0c1b9b47aafbbbfc05ca139865676ac8b3c61；squash c8df994f6710334d7d5397259787b773d39946cc；tag v0.30.20
- 審閱：ChatGPT 2 輪。首審 BLOCK（BLOCK-01：--at 說明「錢進到現貨的時間」不適用轉出；BLOCK-02：讀不到私有競賽 repo 的 docs/capital-flow.md，無法核對工具契約）；複審 PASS（審閱PR#288結論：PASS）。CI run 39937298352，1480 passed。
- 重點：ERR-043 steps 新增一步（競賽餘額差異若是手動轉入／轉出／理財收益，先 preview 再 record；其他三支不需要）；--at 改成「這筆轉入、轉出或收益實際發生的時間，帶 +08:00」；ai_prompt 補資金進出判斷；守門測試白名單加 <金額>；風險登記冊頁面重新產生。
- 教訓：競賽 repo 是私有，審閱者讀不到時，把 exact-head 原文（含 commit 與 blob SHA）貼成 PR 留言當證據，複審即解除；給操作員貼的指令，佔位符的時間語義要對所有種類成立（轉入、轉出、收益）。
- 隔離：審閱端未接觸主機、交易所、帳本。
