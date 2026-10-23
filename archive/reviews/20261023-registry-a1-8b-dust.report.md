# 審閱歸檔 — 登記冊同步 A1 部署（PR #291，8b／f-67／f-66）

- **Repo**：bcup02/trade-alerts
- **PR**：#291，squash 合併為 `39a16258de958b72b1a96f41a43467ad00e60457`；base `601639b8da78ff303817e6acd874e088be8413cd`（main）
- **審閱者**：ChatGPT — 首審 BLOCK（head `0058b38d71628aab4988359bd791ede0a93d639c`）→ 複審 PASS（head `06cbb42018cf801b2ed996b0a16234dbc5dc1eb1`），共 2 輪
- **CI**：pytest = success（首審 run `39946394701`、複審 run `39948022028`；皆 1480 passed，無新增測試）

## 做了什麼

2026-10-23 台北 19:14–19:17 四支策略部署 A1（operations：趨勢 1568826、動能 03fef20、加密 599c607、競賽 9a6b0c9）後，登記冊 `sources` 四個提交換版；既有引用用 `verify_registry_evidence.py --relocate` 搬 49 筆、人工處理 3 筆（動能 funding-sync.timer 加 UTC 字樣仍每 4 小時；趨勢 PROTECTION_MOVE_DEFERRED :1002→:1041；競賽 runner.py 兩提交間 0 行差異）；獨立腳本逐筆比對搬動的 50 筆「舊提交行文字＝新提交新行號行文字」：50/50 相同。7 格改已做：能力 `ledger.dust_convert`（競賽）＋ `FLEET.PROJECTION_TRADE_ID_CONFLICT_PARKED` 行為格與事件日誌格 × 趨勢／動能／加密。

## 審閱 BLOCK 與修正

- **首審 BLOCK-01**：換 sources 後，`FLEET.PROJECTION_ORPHAN_CLOSE_PARKED` 趨勢、動能行為格仍寫「A1 三支策略的 venv **現在**都載入 trade-alerts 0.30.4、blob 400c681」，與同一份登記冊新格的 0.30.19、583bc2e 互相矛盾。修：全登記冊重搜版本／blob／venv／「現在」字樣，改了 9 處（ORPHAN 趨勢動能 2＋加密 3（行為 1、事件日誌 2 句）、park_unconfirmed 趨勢動能「釘 v0.28.0」改現況＋加密 1、google_projection_grace 加密 1），並把三段 2026-10-16 的 A1 查證段落（docs/registry-a1-checks.json）改成 2026-10-23 的重新量測（verified_at 同步，既有測試要求一致）。有日期的歷史部署量測與「功能出現在哪一版」不是 A1 現況宣稱，保留。
- 教訓：**換 sources 時除了 file:line，還要全搜「A1 現在載入什麼版本」這類現況句**——verify_registry_evidence.py 完全看不到；改完用 grep 確認沒有無日期的舊版本號。

## 發布與觀察區

- 合併後重發兩張登記冊（風險登記冊 Version 56、一致性登記冊 Version 76）。
- 刻意沒做、另開：8b 第二批已在 A1，趨勢 ERR-003／ERR-005 與多個「寫進事件日誌」格仍寫未做（過時），要逐格找 A1 證據。
- 審閱者界線：沒有連線 A1 重新量測，只核對留言證據的內部一致；沒有本地跑 render_guides --check；PASS 不授權合併以外的任何實機操作。隔離：只讀 GitHub，未接觸 /opt、/etc、/var/lib、systemd、交易所、Google、實機帳本。
