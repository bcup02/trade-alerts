# 登記冊 x7：加密 A1 切到 Binance 主網真倉 審閱歸檔

- PR：bcup02/trade-alerts#216
- head：3b59243d273054764dc8962cb00752a16d3e1311／ base：8c63e7b72cf7dee253843ec7fc841f4f597a30c2 ／ squash：b22574e
- 審閱：ChatGPT，1 輪 PASS（審閱PR#216結論：PASS）
- CI run：39022605856（1078 passed，無新增測試）
- 重點：2026-10-17 台北 17:30 起 A1 加密是 Binance 主網真倉。改寫 9 種過時限制句共 26 處（A1 加密 OFFLINE／exchange.env 是 mexc／要等 x5、x6）；沒有任何格子 state 改變；phases.x3-crypto-binance、updated_at、recent_changes（11 cap、11 rule 用 updated）；sources.mycrypto 5461832 → a0727d3d38a2b83e18898d3583843c53aba5bb60。
- sources 換版證據：兩提交間非歸檔變動檔 7 個（docs 3、scripts 2、tests 2），登記冊引用的 file:line 無一落在其中；verify_registry_evidence.py 0 problems；A1 /opt/my-crypto-bot 內 .py、scripts、deploy 共 60 檔與 a0727d3 逐檔 sha256 比對 59 相同，唯一不同是不部署的 archive/ 檔。
- 審閱非阻擋建議：recent_changes 的 22 筆 note 措辭相同，可日後更精準指出未觸發的子路徑；審閱端沒有重新量測 A1 或 Google，營運事實由 PR 提供。
- 隔離聲明：審閱端只讀 GitHub；PASS 不授權部署或變更 A1。
