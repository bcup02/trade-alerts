# 登記冊 x7a：下單取整修正（工具庫 0.4.1）審閱歸檔

- PR：bcup02/trade-alerts#218
- head：3d7c7f30e485ef305a156b304b399237745f2447／ base：1b4ec06e9fde10d85aff4b1271d3221793b2c2c0 ／ squash：6f8c3cf
- 審閱：ChatGPT，1 輪 PASS（審閱PR#218結論：PASS）
- CI run：39045039532（1078 passed，無新增測試）
- 重點：新增 capability orders.step_rounding_decimal（趨勢、動能、加密＝已做，引用釘選行與守門測試 :9／:16／:21；競賽＝不適用，自己的 rebalance.py:126 取整加 1e-10 補丁）；沒有既有格子的 state 改變；recent_changes 改成單一 added；sources 換版：趨勢 9e487c0e→ef0d809b、動能 71e60471→b92a10b1、加密 a0727d3d→096b9e8d。
- sources 換版證據：verify_registry_evidence.py 340 筆引用逐筆比對 0 shifted／0 changed／0 未配對／0 略過、0 problem(s)；A1 /opt 各策略 .py／scripts／deploy／src 與新 sources 提交逐檔 sha256 比對：趨勢 57/57、動能 76/76、加密 59/59 相同。審閱端獨立抽查三處舊新同行文字一致。
- 審閱注意：競賽的 floor(value/step+1e-10) 補丁不是十進位精確保證，「沒有發現同樣問題」只是目前觀察結果，競賽自身取整可靠性應另案審；審閱端沒有重跑腳本與 render check、沒有連 A1，部署與對帳結果採 PR 提供的紀錄。
- 隔離聲明：審閱端只讀 GitHub；PASS 不授權部署。
