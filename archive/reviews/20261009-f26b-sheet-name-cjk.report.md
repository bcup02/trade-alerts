# Perplexity 審閱歸檔 — Google 表逐筆分頁名稱允許中文（f-26b 第 1 步，PR #154，v0.29.1）

- **Repo**：bcup02/trade-alerts
- **PR**：#154，最終 head `39c5d86d18feff78c923a96ece4bacaf62eb5c9c`，base `944b078275cc866c9fd24cccc0489cc6b98c0451`（main），squash 合併為 `c19a3e7`；tag `v0.29.1`（annotated，tag 物件 8f2ce3d）指向 c19a3e7
- **審閱者**：Perplexity — 兩輪：首審 **BLOCK**（兩項）→ 複審 **PASS**
- **CI**：pytest = success（最終 run `37885783817`；763 passed）

## 做了什麼
`ledger_integrity.py` 新增 `_SHEET_NAME_RE` 與 `_require_sheet_name`，讓 signed_request／signed_reconciliation_request／signed_read_audit_request 接受中文分頁名（趨勢策略等）；其餘識別字（project_id、source_id、trade_id）不變。版本 0.29.0→0.29.1，runbook 補一筆，新增 tests/test_sheet_name_cjk.py。

## 審閱過程
- 首審 BLOCK-01：用 Python `\w` 會放行韓文填充字 U+3164／U+FFA0／U+115F、全形字元、帶圈／上標數字，這些看起來像正常名稱但與接收端登記的名稱不相等（結果是請求長期被 source_not_allowed 重試）。BLOCK-02：長度上限從 256 縮成 100，runbook 卻寫「完全照舊」。
- 修正：改明確白名單（ASCII 識別字元＋CJK 統一表意文字 U+4E00–U+9FFF 與擴充 A U+3400–U+4DBF），長度回到 256；窮舉測試比對舊 ASCII 契約。審閱者全範圍 Unicode 掃描與 2,113,664 個 ASCII 字串比對零差異。
- 審閱者聲明：沒有實際呼叫 Apps Script，Python／Node 離線 HMAC 24/24 一致；DEV 接收端實測不屬本 PR。非阻擋建議：把 U+F900、U+2F00 的拒絕案例加進單元測試（未做，記在後續）。

## 教訓
- 放寬輸入驗證時用「明確白名單」，不要用 `\w` 這類依賴 Unicode 分類的簡寫；放寬前先想「會與誰逐字比對」（這裡是接收端登記名）。
- 縮減既有契約（長度）要同時改向後相容的文字，並用窮舉測試鎖住舊契約。

## 隔離聲明
共用庫程式與測試；沒有部署、主機、交易所、Google 或帳本接觸。
