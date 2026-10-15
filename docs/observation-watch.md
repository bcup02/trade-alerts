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

## 它能證明什麼、不能證明什麼
- 「事件發生」「第一則送出」「第二則送達」是三件事，分開寫在證據裡：事件看帳本與事件日誌；第一則看維運通知的狀態檔（`delivered`／`notified_at`）與日誌的 `sent=attempted`；
  **第二則的成功維運通知不記錄**（只記失敗），所以永遠不宣稱它送達，一律問人。
- 維運通知狀態檔的 `delivered` 不一定是真的送出：它第一次看到某個策略時，會把當時已存在的通知全標成 `delivered` 但**不發送**。所以事件早於該策略的 `baseline_at` 時，送出紀錄不算證據，結果會明寫「無法證明有送出」並請你確認有沒有收到。
- Google 對帳的 `RECONCILED` 只有在**對帳時間晚於那筆新交易的 61 分鐘寬限之後**才算數（新交易 60 分鐘內本來就可以還沒上表）；之前的 RECONCILED、寬限內的 RECONCILED、過期（超過 90 分鐘）的都不算，只會繼續等待。
- 已知限制：Telegram 送出但狀態檔存不進去時，下一輪可能重複發送（會印出錯誤並以結束碼 1 結束）；同時只會有一個在跑（檔案鎖）。
- 受控測試事件靠 `details.test`／`evidence.test` 排除；維運通知日誌本身分不出測試與真實，所以狀態告警那一項一律要人確認。

## 唯讀與安全
- 只讀固定清單內的檔案與日誌（`Remote` 的白名單是**確切的路徑清單**與 `ops-notify.service`，時間用 `fullmatch`；不是「符合某種樣式的任何檔案」）。A1 用 `ssh … sudo cat／journalctl`，開發機用 `sudo -n cat`。注意：主機上該帳號能 `sudo` 什麼是另一層、比這個工具寬的權限，這個工具靠白名單把自己限制在清單內。
- Telegram 設定放在 `/etc/observation-watch/watch.env`（root 0600，只有 token 與 chat id）；程式不印出、不寫入日誌。
- 測試用的受控事件（`details.test` / `evidence.test`）一律不算。

## 登記冊等部署的格子（`registry-awaits`，phase-sync1）
一致性登記冊的「已做」＝正式機（A1）上在跑。以前「上線後改已做」只靠記憶，2026-10-15 重讀才發現 38 格 10/4 就上線了還寫未做。現在：

- 未做的格子如果在等某個部署，要在該格寫 `awaits_commit`（那支策略 repo 的提交，7～40 位小寫十六進位）。理由寫了「上正式機後改已做／還沒上正式機／未部署／未發版」這類話卻沒填，`registry_problems`（CI）會擋。
- `registry-awaits` 每 30 分鐘做三件事：從 `origin/main` 讀登記冊；問 A1 各策略部署用複本（`/home/ubuntu/src/<repo>`）現在在哪個提交（只准 `git rev-parse HEAD`，目錄是固定清單）；用開發機上同名 repo 的 `git merge-base --is-ancestor` 判斷等的提交是否已包含在內。
- 已包含 → 狀態 `observed`＋`needs_human`，Telegram 點名是哪幾格：照格子的證據欄補 A1 查證後改已做、重發登記冊。還沒 → `waiting`。等的提交在本機找不到（寫錯或沒推上遠端）→ `error`（連續 3 次通知），不會默默當成沒事。
- 限制：「A1 部署複本的 HEAD」是部署的代理——部署流程是先 pull 再跑安裝腳本，兩步之間或只 pull 沒安裝時會不準；要確認實際在跑的檔案用格子裡的 `git hash-object` 比對。開發機的 repo 要能 fetch（工具會先 `git fetch`，失敗不致命）。
- 不在這個檢查範圍：不寫 `awaits_commit` 的未做格子（例如等手機測試、等使用者決定、等還沒開 PR 的工作）——這些沒有提交可比對。

## 登記冊引用的檔案在 A1 上變了（`registry-drift`，phase-sync4）
一致性登記冊每個「已做」格子的證據引用 `檔案:行號`，那是 `sources` 提交上的位置。A1 之後部署了別的版本，檔案可能改過、行號位移、說法不再成立，而格子還寫著當初的樣子。

- 每 30 分鐘：讀 `origin/main` 的登記冊，收集所有已做格子引用的檔案；對每支策略，比較「`sources` 提交上那個檔案的 blob」與「A1 部署複本（`/home/ubuntu/src/<repo>`）HEAD 上的 blob」（A1 端只准 `git ls-tree -r HEAD -- <路徑>`，路徑要長得像 repo 內相對路徑）。
- 有不同 → `observed`＋`needs_human`，Telegram 點名是哪幾個檔案、影響哪幾格；key 含 A1 上的 blob，A1 又改了會再通知一次。全部相同 → `waiting`。`sources` 提交在本機找不到、登記冊 repo 抓不到最新（fetch 失敗）→ `error`。
- 處理：看那個檔案從 `sources` 到 A1 現行版改了什麼；行號位移就照 f-27／f-18 的流程把該策略的 `sources` 換到 A1 現行版（`verify_registry_evidence.py --relocate`，逐筆比對舊新行文字），並重新確認受影響格子的說法；換完偵測自己恢復 `waiting`。
- 限制：只比對「引用到的檔案」，不看檔案改了什麼，所以改了無關的行也會點名（寧可多報）；A1 部署複本的 HEAD 是部署的代理（見上一節）；只讀「已做」格子的 `evidence` 欄，未做格子的 `reason` 不算。

## 新增一個檢查
在 `scripts/observation_watch.py` 寫一個 `check_xxx(ctx) -> Result`，加進 `CHECKS`（`covers` 填進度頁項目編號），
在 `tests/test_observation_watch.py` 用 `FakeRemote` 寫：等待、通過、失敗各一個測試。判斷不到的事（手機上看到的樣子）設 `needs_human=True`，不要假裝能自動驗證。

- 狀態檔在取得檔案鎖「之後」才讀（`run` 與 `ack` 都是）：排在另一輪後面的那一輪，依前一輪存下的結果決定要不要通知，不會用鎖之前讀到的舊狀態重複發送。`ack` 會等鎖（等到前一輪結束），`run` 遇到鎖仍是略過這一輪。
