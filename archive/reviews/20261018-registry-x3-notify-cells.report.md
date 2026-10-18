# 登記冊 x3：加密通知兩格改已做（A1 受控測試）審閱歸檔

- PR：bcup02/trade-alerts#220
- head：08084c77f5a889af3c7e6273d39ea96082d59fc0（首審 head 0bee6672efb2b52a748792c4cbb503ca9a587e77）／ base：38e23109df6f63dc48f2b7ec3fc7e7292b9d6118 ／ squash：870b1fa
- 審閱：ChatGPT，2 輪（首審 BLOCK、複審 PASS：審閱PR#220結論：PASS）
- CI run：39095149042（1078 passed，無新增測試）
- 重點：notify.line_first_notice、notify.error_id 的 mycrypto 兩格 pending→done，依據 2026-10-18 台北 A1 受控測試（人工寫入標明【測試】的 ERR-066 事件，經匯出檔與維運通知，使用者手機收到兩則，下一輪 attempted=0 未重送）；evidence 縮成程式依據＋file:line，A1 測試經過與手機原文放 docs/registry-a1-checks.json；ERR-066 自己的 emits_event 限制句與 ops_notify.export_relay_enabled 加密格過時說法一併更新。
- 首審 BLOCK 三點：①notify.error_id 缺手機端第一行（【ERR-066】＋標題）證據→使用者貼回原文補上；②R3 行號 fleet_events.py:37 應為 :45；③同一 ERR-066 的 emits_event 限制句與新宣稱矛盾。教訓：（a）改語意要整句搜全 JSON，連同「同一事件的其他格」；（b）「已做」的證據要和該格定義完全對得上（第一行格式要有手機原文）；（c）先跑 render_guides.py --check／verify_registry_evidence.py／pytest 全套再推，登記冊有字數上限（evidence 700／limit 300）與歸檔規則（A1 長段落放 registry-a1-checks.json、header 要有「唯讀查」才解析查證日），第一版修正因此 CI 失敗了一次。
- 審閱注意：測試事件是人工寫的，策略自己偵測到接管並寫出事件的路徑在 A1 還沒發生過；審閱端沒有連線實機，A1 結果採 PR 與歸檔提供的使用者確認資料。
- 隔離聲明：審閱端只讀 GitHub；PASS 不授權部署。
