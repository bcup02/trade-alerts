# Perplexity 審閱歸檔 — 對帳：接手倉位與原生停損平倉的成交不再被誤判成「帳本沒記」（PR #117，v0.27.0）

- **Repo**：bcup02/trade-alerts
- **PR**：#117，最終 head `911ac615d19e19b36988406897716a5addb42bfa`，base `361d0d3ec91ef3a624c81af49d94b959ae9b6a2c`（main），squash 合併為 `b1e8df3`
- **審閱者**：Perplexity — 五輪：`fe84db9` BLOCK（F0 時間戳缺失）→ `e98a53a` BLOCK（F1 bool／0.5／溢位、F2 NaN 成交時間被舊過濾丟掉）→ `28b8cde` BLOCK（F3 NaN 價量被當一致）→ `911ac61` **PASS**
- **CI**：pytest = success（最終 run `37279965376`；630 passed，起始 459）

## 做了什麼

2026-10-03 開發機趨勢策略接手一筆倉位，兩筆真實成交因為帳本列（`position_recovered`、原生停損後的 `trade_close`）沒有 `order_id`，對帳靠 order_id 配對而一直 DIVERGED。使用者選方案 A：用時間、價格、數量配對。

- `match_fills_to_adopted_events`：只在同交易對、方向正確、數量與價格完全一致（容忍度 1e-9／價格×1e-9）、成交不晚於帳本列且最多早 12 小時時，才算帳本列解釋了那筆成交；每列至多解釋一筆；乾跑、非 LIVE／DEMO、帶 order_id 的列不用。
- `exchange_ledger_compare`：被解釋的成交從 `unmatched_exchange_fills` 拿掉，`evidence.fills_matched_to_adopted_events` 逐筆列出。版本 0.27.0。

## 審閱過程（每一輪都是同一類缺陷：「無法證明一致」被當成「一致」）

1. 首審 BLOCK：時間缺失／0 被 `to_float` 轉成 0，兩邊都沒時間就「對上」。修正：兩邊都要有效正數時間。
2. 二審 BLOCK：`_positive_ms` 接受 `True`、把 `0.5` 截成 0、`10**400` 溢位；NaN／+inf 成交時間在寬限過濾那行（`(time_ms or 0) < …`，前一版就有）被悄悄丟掉。修正：時間必須是有限數且 ≥ 1，溢位視為不可用；時間讀不出來的成交一律保留。
3. 三審 BLOCK（F3）：`abs(a−b) > tol` 遇 NaN 為 false，NaN／"nan" 價量被當一致，端到端回 RECONCILED。修正：價量兩邊先過 `_finite_positive`，容忍度改成肯定式比較；同一類寫法的部位比較兩處（NaN 帳本部位被丟掉、NaN 差值不算差異）一併修；`numpy.bool_` 與 bool 同樣拒絕。
4. 四審 PASS：審閱者實測 F3 的四個重現、實際 numpy.bool_、104 個定向案例全部通過；有限數的原容忍度邊界不變。

## 審閱者標明的界限與後續

- PASS 只限本 PR 範圍，不代表整個模組已消除所有 NaN 問題。審閱者另指出未被本 PR 改動的 Google 表比較缺口：`_value_mismatch`（`ledger_reconcile.py:749` 出場價差、`:755` 損益差）以 `>` 判斷，sheet 欄位為 "nan" 時回 None、不列差異。已另列待辦。
- `_is_boolean` 以型別名稱判斷，可能保守拒絕同名自訂型別，只會不配對，不會藏起成交。
- 亂碼「字串」的帳本時間仍由既有 `> cutoff` 比較丟 TypeError；審閱者沒讀各策略外層，未獨立確認一定轉成 UNKNOWN。
- 沒有發 tag；趨勢策略自己的 `compare.py` 是獨立副本，要另外接上並改釘；動能改釘後生效（且要實測 `is_paper_event` 對無 order_id 平倉的影響）。

## 隔離聲明

審閱者唯讀；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或實機帳本。合併不代表任何主機部署。
