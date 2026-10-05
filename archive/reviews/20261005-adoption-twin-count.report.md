# Perplexity 審閱歸檔 — 同一次開倉的接手紀錄與開倉紀錄只算一次（PR #123，v0.27.3）

- **Repo**：bcup02/trade-alerts
- **PR**：#123，最終 head `d48ea531ec1d2dfa2f47a2bcccc18bb8923288b7`，base `2ab3ca8e4f1a800ef54e3c1b2cbc48ab9559590e`（main），squash 合併為 `077f66a`，tag `v0.27.3`
- **審閱者**：Perplexity — 四輪：`4011087` BLOCK（F1 同 trade_id 不足以證明同一次開倉、F2 不可 hash 的 trade_id 丟 TypeError）→ `924fe66` BLOCK（F3 只要有一個連結相同就收合，忽略另一個識別值的明確矛盾）→ `d48ea53` **PASS**
- **CI**：pytest = success（最終 run `37293673164`；662 passed，起始 639）

## 做了什麼

動能 #118（讓 `position_recovered` 也算開倉）首審 BLOCK：動能中斷進場被接手時，`strategy.py` 先寫 `position_recovered` 再對同一 `trade_id` 寫 `trade_open`（同一次開倉的兩筆紀錄），`_ledger_positions` 逐筆累加，帳本部位變兩倍（recovered 3.0＋trade_open 3.0 對交易所 3.0 → 帳本 6.0）。共用庫新增 `_adoption_twin_positions`：一列 `position_recovered` 只有在存在「同 `trade_id`、同交易對、數量相同、不晚於快照、有共同連結（相同的 `recovered_from_attempt_event_id` 或 `order_id`，兩側非空）、且沒有矛盾（兩側都帶的識別值必須一致）」的 `trade_open` 時才不計入；一對一；證明不了的照算。新增 `_id_text`（只收非空字串或整數）。23 個新測試。

## 審閱過程（每輪都是「收合條件還不夠嚴」）

1. 首審：第一版只看同 `trade_id`，接手後的真正加碼（同 `trade_id`、不同 order）被一起吞掉，交易所只剩 1.0 時帳本算 1.0 而非 4.0，回 RECONCILED；list／dict 的 trade_id 在 membership 檢查丟 TypeError。修正：trade_id 只當候選，改要共同連結＋數量相同＋一對一；識別值先過 `_id_text`。
2. 二審：只要 attempt 或 order 其一相同就收合；同 attempt 不同 order（兩張單）仍被收合。修正：先拒絕任何兩側都有值而不相等的識別對，再要求至少一個相同連結。
3. 三審 PASS：審閱者驗證兩個矛盾方向、81 組 attempt／order（缺失／值 1／值 2）連結矩陣、兩對交叉一對一、快照夾在兩次寫入之間、預設呼叫端與 v0.27.2 一致。

## 審閱者標明的界限

- 「證明不了就照算」是 fail-closed 方向，但不是「永遠不會藏住任何差異」的全域保證（完整結果仍受平倉、標記等事件影響）。
- 對趨勢、加密只就函式契約判斷，沒有跑那些 repo 的測試。
- Google fold 未改（雙紀錄時取先寫的 recovered，歷史上它可能沒有 order_id）；動能 #118 要補歷史雙紀錄的消費端回歸。
- PASS 不授予部署、發 tag 或改釘權限。

## 隔離聲明

審閱者唯讀；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或實機帳本。合併不代表任何主機部署。
