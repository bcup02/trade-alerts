# PR #311 R033 競賽熊市持有 PAXG——ERR-070、登記冊項目、名詞（v0.30.21）

- PR：bcup02/trade-alerts #311；base a6726ead8fc5242b949745f4898a83de82543fa0；squash 0df07fe13a0ca59e8ba2d698c3d4b7d2298de60f；tag v0.30.21
- 審閱：ChatGPT 2 輪。首審 head 1aa379be3bbf28ef9d795258c5146c0966d7ba2e **BLOCK**（兩項）；複審 head 5115f78a35ac868e4207d0f8b7335b0774e9cd65 PASS（審閱PR#311結論：PASS）。CI run 40644878440／40649205192，皆 1570 passed（baseline 1570，只改資料）。
- 重點：錯誤清單新增 ERR-070 BTC.PAXG_DATA_UNAVAILABLE（R2、JUDGEMENT、連續 3 個 UTC 日讀不到 PAXG 行情才通知一次；使用者 D5 決定）；登記冊新增階段 r033-paxg、能力項目 bear.paxg_asset（競賽 pending、其餘三支 n/a）、規則列 BTC.PAXG_DATA_UNAVAILABLE（兩格 pending）；名詞對照表加「PAXG（黃金代幣）」「PAXG 多頭指標」；兩頁重新產生；版本 0.30.21。
- **BLOCK 與教訓：** (1) 操作訊息寫「讀不到的期間策略一直是全 USDT，不會虧損」「PAXG 已賣回」——把目標當成已確認結果、還保證沒有價差損失；賣單可能被拒、未完成或成交價與估值不同。改成目標與實際分開寫，並要求先確認實際倉位、成交、待完成目標與安全暫停。(2) R2／JUDGEMENT 通知卻寫「不需要做決定」，與步驟（查交易對是否下架、決定要不要關 PAXG）矛盾；改成「需要你判斷」並說明判斷什麼。教訓：給維運人員的訊息，目標配置與實際成交要分開寫，不能無條件保證結果；JUDGEMENT 的訊息一定要說清楚要判斷什麼。另：第一版把 verdict 寫成 MECHANICAL，被既有測試擋下（R2 通知必須是需要判斷的情況），改 JUDGEMENT。
- 審閱者備註（非阻擋）：步驟裡「該次執行會把它賣回 USDT」未來可改成「會嘗試按換倉流程賣回」；sources 指向策略 repo `runner.py:768`（development），策略端下一個 PR 若移動函式要同步更新；兩個 HTML 審閱者讀生成檔而非逐行 patch，也沒有在獨立環境重跑產生器。
- 部署：不用部署（資料）。合併後打 tag v0.30.21 供策略 repo 引用。
- 隔離：審閱端未接觸主機、交易所、帳本；未動任何 .py。
- 歸檔註記：patch 不含 docs/guides 的兩個產生頁面（由 render_guides.py 產生）。
