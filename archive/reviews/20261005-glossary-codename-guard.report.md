# Perplexity 審閱歸檔 — 錯誤目錄說明改用策略中文名＋裸英文代號守門測試（PR #115）

- **Repo**：bcup02/trade-alerts
- **PR**：#115，head `466e292a0795561d9dc3af6114d1cf13892b99f3`，base `8085ade0eac45c31bb35469bd5d2f3e8d420de1b`，squash 合併為 `c7cf66b`
- **審閱者**：Perplexity — 一輪 **PASS**
- **CI**：pytest 等檢查 = success（run `37264688924`；458 passed）

## 做了什麼

錯誤目錄 12 個條目的 rationale／human_action／operator_message 共 19 處中文句子裡的裸英文代號（seykota／momentum／my-crypto）改成趨勢策略／動能策略／加密策略；ERR-008 的 rationale 追加 2026-10-05 後端逾時事件說明；登記冊 1 處證據文字、updated_at 與 recent_changes（13 個動到的目錄條目）更新；新增 `glossary.bare_codename_hits` 與守門測試（掃目錄與登記冊全部字串值，不掃鍵名，反引號與帶 -／／／. 的識別碼不算）；兩張登記冊頁面重新產生。

## 審閱備註

審閱者逐欄比較 JSON：恰 17 個變動字串、結構與判定欄位零變更、sources 零變更、recent_changes 13 列與實際變動條目集合相同。審閱者未自行重跑 render_guides／verify_registry_evidence（依 CI 與 PR 記錄），未讀兩張產生頁的全部未變動原文。審閱者指出 trade-alerts 沒有 testing 分支（以 main 為合併目標），並建議把 ERR-008 的「一律算暫時性」改寫成「在唯讀查詢分類路徑算暫時性」（非阻擋，未做）。

## 隔離聲明

審閱者唯讀；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或實機帳本。合併不代表任何主機部署。
