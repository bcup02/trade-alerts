# PR #381 審閱歸檔：登記冊 PAXG 錯誤規則四格改已做（v0.30.43）

- PR：bcup02/trade-alerts #381；squash `ae104be`（tag `v0.30.43`）；審閱 AI：ChatGPT；結論：第 1 輪 BLOCK（head `8441549`）、第 2 輪 PASS（head `e75f544`，CI run 44233686897，1670 passed）。
- 範圍：`BTC.PAXG_DATA_UNAVAILABLE`（ERR-070）與 `BTC.PAXG_RULE_MISSING`（ERR-071）在 btc-competition 的 behaviour／emits_event 四格由 pending 改 done；`phases.r033-paxg` 說明、`recent_changes`、`updated_at`；兩張登記冊頁面重新產生；版本 0.30.43。`sources` 沒換（競賽仍 `32331cb`）。

## 審閱歷程
| 輪 | head | 結論 | 內容 |
|---|---|---|---|
| 1 | `8441549` | BLOCK | ERR-071 emits_event 的 evidence 寫「規則回來才結束這一輪」；實際 `runner.py:571-572` 只要缺規則條件不成立（包含 PAXG 持有量歸零）就清通知旗標，`tests/test_runner_paxg.py:616-631` 有直接反例 |
| 2 | `e75f544` | PASS | evidence 改為「條件不再成立（規則恢復，或 PAXG 已不再持有）就清旗標，之後再成立會重新通知」；並採納審閱建議，在 ERR-070 behaviour 的 limit 補「持有 PAXG 卻取不到成交價時本次執行中止（`runner.py:831`）」 |

## 查證依據
- 正式機分支 `operations` = `32331cb`；A1 上 `runner.py`、`fleet_events.py` 的 sha256 與 operations 相同；A1 競賽用共用庫 `trade_alerts 0.30.23`，兩個代碼在該版錯誤清單內。
- 在 operations 版配共用庫 v0.30.23 跑 `tests/test_runner_paxg.py`：43 passed。
- `verify_registry_evidence.py`：0 problem。
- 隔離聲明：審閱者只讀 GitHub PR、repo 檔案與 Actions 日誌，未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或實機帳本。

## 部署／重發
- 登記冊：台北 2026-11-18 兩張頁面 `--check-published` 皆 STALE，直接重發（風險登記冊第 73 版、一致性登記冊第 104 版）。
- `sources` 沒換，不用送 bundle 給開發機。

## 已知缺口與後續
1. 這兩種狀況在 A1 沒真的發生過；事件寫進日誌後 LINE 是否送達沒有實測（四格 `limit` 已寫明）。
2. A1 檔案雜湊與共用庫版本是開發端查證，審閱者依 SOP 沒連線 A1。

## 教訓
1. 登記冊 evidence 的句子要逐句對照程式與測試，不能憑測試名稱寫：`test_the_rule_coming_back_ends_the_episode...` 的名字只講規則回來，內容卻同時驗證了「持有量歸零也結束」，我照名字寫窄了。
2. 寫「結束／重置條件」時，要回到判斷條件本身（`_paxg_rule_missing` 的所有 False 分支），不要只寫最常見的那一個。
