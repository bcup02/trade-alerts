# ERR-068 SEY.CORRECTION_BASE_MISMATCH（趨勢兩筆舊單第二次更正會被拒收）審閱歸檔

- PR：bcup02/trade-alerts#240
- 第 1 輪 head：5910f51e9179641ff08e7a5c26d4647a4c5295c2 ／ 第 2 輪 head：a2ec044b19230b864ab1983a9c2dbcafad83ede1 ／ base：1a59dcce7895e94b1f52eed3bd4c39573b89a490 ／ squash：01981be5e2e65b000f720bec98233301a68c322d；tag v0.30.12 打在 squash commit
- 審閱：ChatGPT，2 輪（第 1 輪 BLOCK B1，第 2 輪 PASS：審閱PR#240結論：PASS）
- CI run：39235465624（第 1 輪）、39239615422（第 2 輪）；皆 1115 passed、0 skipped、Apps Script node 四支通過
- 重點：新增 ERR-068（R1、MECHANICAL、未發事件）與一致性登記冊 SEY.CORRECTION_BASE_MISMATCH 列（behaviour/seykota 已做、emits_event/seykota 未做；A1 唯讀查證 2026-10-19）；版本 0.30.12；兩張頁面重新產生。
- B1（BLOCK）：人工處理指引只列淨損益／數量／備註，漏了整筆更正會寫的其他欄位（進場價、出場價、手續費、毛損益、報酬率、出場訂單編號），也沒揭露手改儲存格不會更新接收端稽核摘要（之後再更正仍會被拒收），忽略清單用途也沒限定。修正：改成逐欄對照帳本最新 trade_correction 的 corrected、明寫手改不更新摘要、忽略清單只影響對帳比較不代替修正、保留「尚未演練」警語、「其他交易不受影響」限定為沒有跨版本更正鏈的交易，登記冊 limit 同步。
- 審閱指出（非阻擋）：①若日後正式演練 ERR-068，U 欄備註的來源建議寫成「依最新 trade_correction 生成的 correction_note」，避免把 corrected 誤解為含備註文字。②A1 blob 雜湊、timer 狀態、兩筆 CONFIRMED 紀錄與摘要重建數字是提交者提供的既有唯讀查證紀錄，審閱者沒有存取 A1 重新量測。③手動處理步驟尚未實際演練。
- 後續：合併後打 tag v0.30.12、重發兩張登記冊；消費專案不必為這個版本改釘（只有資料與版本號）。ERR-068 在 A1 目前不會發生，要等趨勢 v0.30.11 部署上 A1 才生效。
- 隔離聲明：只改錯誤清單／登記冊資料、文件與版本號，沒有程式或函式簽名變更；PASS 不等於部署授權。
