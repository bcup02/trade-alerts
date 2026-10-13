# f-41 狀態告警第二則加上可貼上的唯讀指令（f41-status-ai-commands）審閱歸檔

- PR：bcup02/trade-alerts#180
- head：e605cc2 ／ base：5b2992b ／ squash：bb9ade2467b75e100d3f538338b8d6ae99317404（tag v0.30.6）
- 審閱：ChatGPT，1 輪 PASS（審閱PR#180結論：PASS）
- CI run：38344610530（889 passed，baseline 884，+5 新測試）
- 重點：錯誤清單 ERR-043／044／046／047／048／049 的 ai_prompt（維運通知第二則）加上 A1 上可貼的唯讀指令（sudo cat／ls／journalctl／systemctl status／chronyc tracking）；第一則 steps、欄位、編號、等級不動。守門測試：六條都要有指令、唯讀白名單（含 repo 目錄名）、bash -n 與引號外不得有 < >、其他錯誤的追查指令不得夾帶未審指令、第二則渲染得出指令；手動換成 restart 驗證守門會失敗。
- 審閱留下的非阻擋建議：①白名單比對改用 fullmatch()（現用 match＋^…$，$ 可匹配結尾換行，現有內容沒有可利用情形）——併入 trade-alerts 下一個程式 PR；②具 sudo 的 journalctl 輸出可能含敏感值，貼給 AI 前要檢查並遮蔽；③審閱端沒有連線 A1，路徑與服務名只靠版本化內容與我的唯讀盤點，指令沒有逐條在 A1 貼上跑過。
- 隔離聲明：只改資料、測試、文件與版本；函式庫程式零變更；PASS 不等於 tag／改釘／部署授權。
