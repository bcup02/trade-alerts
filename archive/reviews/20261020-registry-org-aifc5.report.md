# 登記冊 sources 的倉庫位置改 AI-for-column5（f-9c） 審閱歸檔

- PR：bcup02/trade-alerts#257
- head：114ac95dafe16cc683c0873af37aa898ad946b58 ／ base：70c8a7f4afab1686665c7b14fab19ed4c7391cbd ／ squash：7255a403f13e185e2b3f613da9c888d2288b8b7e
- 審閱：ChatGPT，1 輪 PASS（審閱PR#257結論：PASS）
- CI run：39413903215（1196 passed）
- 重點：四支策略倉庫 2026-10-20 轉移到 AI-for-column5；`sources` 四個 `repo` 欄位、`docs.glossary_adopted` 四格 evidence 的 PR 引用、`registry-a1-checks.json` 21 處、runbook 1 處改新組織；四個 `commit`／`branch` 與所有 `file:line` 引用零變更。`recent_changes` 原 9 筆換成這四格的 `updated`。
- 換版比對：因 sources 提交沒換，用 `verify_registry_evidence.py --repos-root ~` 在 base 與 head 各跑一次，輸出各 480 行逐行 diff 相同（478 ok、0 problem）；審閱端獨立解析 JSON 確認 sources 的 branch／commit 逐值相同、a1_check 21/21 只有 `AI-for-column/`→`AI-for-column5/`。
- 審閱端未獨立驗證：478 筆證據逐項重讀四個倉庫、重跑 `render_guides.py --check`、全倉庫 `git grep`（採開發端聲明）。
- 後續：兩張登記冊已重發（風險 v50、一致性 v67，頁面版本碼 2d935f2d…／9c1a3fb8…）。`docs/guides/oracle-migration-plan.md` 的 `AI-for-column/Engineering-Control-Plane` 不是這四支，沒改。
- 隔離聲明：審閱端未接觸實機；PASS 不授權部署或重釘策略。開發端沒有動 A1 服務，只改四支的 git remote（唯讀驗證）。
