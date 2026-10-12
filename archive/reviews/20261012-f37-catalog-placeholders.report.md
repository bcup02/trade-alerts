# f-37 錯誤清單佔位符加引號（f37-catalog-placeholders）審閱歸檔

- PR：bcup02/trade-alerts#175
- head：dbf3eeb ／ base：4cb0098 ／ squash：07a1d5376538f46b510fecf7adcec5a184bdb341
- 審閱：ChatGPT，1 輪 PASS（審閱PR#175結論：PASS）
- CI run：38203349876（870 passed（baseline 857，+13））
- 重點：錯誤清單 operator_message 步驟裡 --confirm／--trade-id／--add-order-id 的佔位符共 23 處加雙引號（不加引號的 <…> 在 bash 是輸入重導向）；新增測試：每條貼上的指令過 bash -n（bash -c 內層另外再過）、引號外不得有 < 或 >、實際用 bash 驗證佔位符是單一參數；風險登記冊頁面重新產生；v0.30.4 tag 已發。
- 審閱留下的非阻擋限制：_outside_quotes 是簡化掃描器、不是完整 bash parser（$'…'、命令替換、here-doc、註解等不能保證攔截）；v0.30.3..v0.30.4 另含兩份 f-35 歸檔檔案（非 runtime）；bash -n 只驗語法。
- 隔離聲明：只改錯誤清單文字／依賴釘版／測試，未改交易、下單、停損、帳本寫入邏輯；PASS 不等於部署授權。
