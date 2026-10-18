# PR #236 審閱歸檔：f-56 第一階段 Google 表「出場原因」欄改中文

- PR：bcup02/trade-alerts #236
- 第 1 輪 head 73ce8561aac413a75ef09603f6a7b2e6eb87bf8b → BLOCK；第 2 輪 6bbdae4e1c7153ab3842bb72fb69d353cf68436e → PASS（審閱PR#236結論：PASS）；base 76d88fe71631a9a95cf1bf09d8723085774c3d71
- squash：0b16630ecd4dff40833d49acea1e9cb16ca895d5
- CI：第 2 輪 run 39152813287，原始日誌 1110 passed；apps_script node 測試通過
- BLOCK 重點（B1）：一次性搬舊資料 convertExitReasons_ 在有任一格要翻譯時對整段 P 欄 setValues，會把公式儲存格換成計算值。修正：先 getFormulas，公式格一律略過，只對匹配的純值單格 setValue；測試加公式列、禁用 setValues、精確檢查寫入位置，並做變異驗證（還原修正測試即失敗）。
- 採納建議：native_stop_reconciled 中文名改「停損觸發或手動平倉（事後補記）」。
- 內容：名詞對照表新增「帳本來源代碼」（28 條目、29 代碼）；接收端 P 欄寫入時翻成中文（未知代碼原樣）；EXIT_REASON_ZH 區塊由 scripts/sync_receiver_exit_reasons.py 從對照表產生並有測試守門；previewExitReasonConversion／convertExitReasonsToChinese 供表格擁有者搬舊資料。
- 審閱者限制：未對全倉庫 source 字面值窮盡盤點；陣列公式展開範圍內的單格寫入可能被 Sheets 拒絕（未預先辨識）。
- 部署：尚未部署接收端；順序 DEV 表 → 問使用者 → 正式表；搬舊資料先預覽再套用。
- 隔離聲明：審閱者只用 GitHub 唯讀資料與 CI 日誌，未接觸 /opt /etc /var/lib、systemd、交易所、Google、實機帳本。
