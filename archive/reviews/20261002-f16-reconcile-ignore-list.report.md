# Perplexity 審閱歸檔 — f-16 共用庫：對帳忽略清單（PR #107）

- **Repo**：bcup02/trade-alerts
- **PR**：#107，最終 head `5c9d467865434ffbf844fa3d203ec70b94cd1220`，base `0090b317e249dd4d42e0e00b6a97d03eca2e4c38`（main），squash 合併為 `1e9d9f51b15587cfcd3f5491019ad5b9802b93d3`
- **審閱者**：Perplexity — 兩輪：首審 head `dd0587c` **BLOCK**，複審 head `5c9d467` **PASS**
- **CI**：最終 pytest = success（run `36984981073`；456 passed，baseline 447）

## 做了什麼

`sheet_ledger_compare(ignore=, ignore_problem=)` 與 `load_reconcile_ignore()`：操作者決定「表上不要了」的交易不參與「帳本↔Google 表」比對，但逐筆列在 `ignored`、計數在 `summary.ignored`、`note` 註明；壞清單整份作廢並顯示 `ignore_list_problem`，不藏差異。順帶修 #105 一個同秒排序不穩定的測試。

## 審閱結論與重點

- 首審 BLOCK（F1）：表端迴圈的 `tid in ignore` 讓「清單有、帳本沒有」的 id 靜默遮住表上多出的列，也不列入 `ignored`。可重現情境：帳本 t1，表上 t1 與 gone，ignore={"gone"} → 應 DIVERGED、實際可 RECONCILED。
- 修正：拿掉該條件（`known_ids` 本來就涵蓋所有帳本交易，包含被忽略的）；新增負面測試（要求 LEDGER_MISSING_ROW(gone) 仍在、ignored=[]）與「無清單／空清單輸出完全相同」測試。
- 複審 PASS：F1 解除；壞清單 fail closed；既有測試未改弱。審閱者標明界限：未建立 exact-head checkout、未本機重跑 pytest；變異測試與 25 次本機重跑為開發端自述；輸出相容性只證明「同一 HEAD 省略清單與空清單序列化相同」，不是跨版本位元組等價。

## 隔離聲明

審閱者唯讀；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或正式機帳本。
