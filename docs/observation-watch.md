# 觀察區自動偵測（f-43）

進度頁的「觀察區」列出要等真實事件才能驗證的事（下一則真實告警、下一筆真實交易、加密策略空手……）。
`scripts/observation_watch.py` 每 30 分鐘在開發機唯讀地偵測這些事件，結果寫進 `~/.local/state/observation-watch/state.json`，
有新的觀察到或失敗時發**一則** Telegram。進度頁由 Claude 開工與收尾時讀這份結果去結案或重開，這個程式不碰進度頁。

## 每個檢查回報什麼
| 狀態 | 意思 | 之後 |
|---|---|---|
| `waiting` | 事件還沒發生 | 什麼都不用做 |
| `observed` ＋ `closable` | 事件發生了，所有判斷都是機器能量的、全部通過 | Claude 附證據結案，再 `ack` |
| `observed` ＋ `needs_human` | 事件發生了，但還要人看（手機、Google 表） | Telegram 問你，你回覆後 Claude 結案 |
| `failed` | 事件發生了但不符合預期 | Claude 重開該項、加進等待決定、查原因 |
| `error` | 檢查本身壞了（連續 3 次才通知） | Claude 修檢查 |

## 指令
```bash
python3 /opt/observation-watch/observation_watch.py report          # 看現況
python3 /opt/observation-watch/observation_watch.py report --json
python3 /opt/observation-watch/observation_watch.py run --dry-run   # 現在檢查一次，不發訊息、不存檔
python3 /opt/observation-watch/observation_watch.py ack <check-id>  # 這一項處理完了（報告不再提醒）
```

## 唯讀與安全
- 只讀固定清單內的檔案與日誌（`Remote` 的路徑與服務名白名單；不接受 `..`、空白、分號）。A1 用 `ssh … sudo cat／journalctl`，開發機用 `sudo -n cat`。
- Telegram 設定放在 `/etc/observation-watch/watch.env`（root 0600，只有 token 與 chat id）；程式不印出、不寫入日誌。
- 測試用的受控事件（`details.test` / `evidence.test`）一律不算。

## 新增一個檢查
在 `scripts/observation_watch.py` 寫一個 `check_xxx(ctx) -> Result`，加進 `CHECKS`（`covers` 填進度頁項目編號），
在 `tests/test_observation_watch.py` 用 `FakeRemote` 寫：等待、通過、失敗各一個測試。判斷不到的事（手機上看到的樣子）設 `needs_human=True`，不要假裝能自動驗證。
