# f-42 唯讀白名單比對改用 fullmatch（f42-readonly-fullmatch）審閱歸檔

- PR：bcup02/trade-alerts#182
- head：e5139b9 ／ base：cd17692 ／ squash：b10a1712b15da8dfb08df954236d4cf61252a37e
- 審閱：ChatGPT，1 輪 PASS（審閱PR#182結論：PASS）
- CI run：38347697554
- 重點：#180 審閱留下的非阻擋建議①。守門測試的唯讀白名單比對由 `match`（`$` 可匹配結尾換行）改為共用的 `_read_only_match`＝`fullmatch`；新增測試：結尾換行、`; rm -rf /` 這類夾帶都必須被擋；把比對改回 `match` 驗證守門會失敗。函式庫程式零變更。
- 隔離聲明：只改測試；PASS 不等於 tag／改釘／部署授權。
