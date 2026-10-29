# PR #323 ERR-071 競賽持有 PAXG 卻找不到 PAXGUSDT 規則（P3c.1，v0.30.23）

- PR：bcup02/trade-alerts #323；base 0d4fc9e355f4ef3fbe7a78d23ef1815379098c02；squash c011ea4baf2b0886fb6b4275a157ef170479f84f；tag v0.30.23
- 審閱：ChatGPT 1 輪，head 8bde3d7148880455364da5c26a40e60ba1a95359 **PASS**（審閱PR#323結論：PASS）。CI run 40815779981，1570 passed（baseline 1570，只改資料）。
- 重點：錯誤清單新增 ERR-071 BTC.PAXG_RULE_MISSING（R2、JUDGEMENT、第一次發現就通知一次，使用者 2026-10-29 決定）；登記冊新增規則列（競賽兩格 pending，階段 r033-paxg）。
- 審閱者備註（非阻擋）：`human_action` 的「PAXG 一直留在帳戶裡」略絕對，未來可改成「未確認成功處置前視為仍可能持有」。通知、去重、歸零是 catalog 契約，端到端要在策略 repo 的 PR 檢查。
- 部署：不用部署（資料）。
- 隔離：審閱端未接觸主機、交易所、帳本；未動任何 .py。
- 歸檔註記：patch 為完整 squash diff，含 docs/guides 的兩個產生頁面。
