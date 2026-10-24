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

## f-70 第一批：原本靠收尾手動查的三項（`dev-trend-reconcile`、`health-publish`、`dust-convert`）
2026-10-24 使用者要求把觀察區「AI檢查」的項目改成偵測程式自動通知。第一批是資料單純、不用記「連續幾天」以外狀態的三項；第二批（A1 健康穩定天數、f-63 同一天只進一次、x5 停損觸發與移動、f-38）見下一節。

- **`dev-trend-reconcile`（f-7 後半）**：開發機趨勢的 `ledger_status.json`。20 張手動測試單留下 25 筆帳本沒記的成交，對帳只看最近 168 小時，所以最後一批滑出窗口（2026-10-27 台北 17:00）後應自動回到 `RECONCILED`。讀數超過 90 分鐘或讀不到是 `error`；`RECONCILED` 為 `observed`（發一則，不算可結案：f-7 的進場那一半由 `dev-trend-entry` 看；那串 UNRESOLVED 請求有沒有自動撤回，這支沒讀）；其他值是 `waiting`。
- **`health-publish`（f-45）**：兩台主機的 `/var/lib/ops-notify/health-publish-state.json`（新增兩個可讀路徑之一；A1 與開發機同一個路徑）。每台「正常」＝`consecutive_failures` 是 0 且 `last_success_at` 在 25 分鐘內。連續 `STABLE_STREAK`（72 小時，預設）每一輪都兩台正常才發「可結案」一則；中間任何一輪有一台不正常就把穩定時間歸零；**前一個看到兩台正常的輪次離這一輪超過 45 分鐘也歸零**（`STREAK_MAX_GAP`；中間有一輪讀不到、讀檔失敗或偵測沒跑，就是看不到的空窗，不能算進連續時間——檢查出錯的那一輪會保留舊的 `extra`，所以靠這個間隔判斷；2026-10-24 審閱 #304 BLOCK-304-01 抓到）。起點與最近看到的時間記在檢查自己的 `extra.healthy_since`／`extra.last_seen`，看不到過去，所以從第一個看到兩台正常的那一輪起算；任一台連續失敗 3 次以上是 `failed`；檔案讀不懂是 `error`。登記冊面板的 A1／開發機分頁有沒有被標過期，這支沒讀，結案時仍要看一眼頁面。
- **`dust-convert`（f-66）**：競賽策略第一次真實的粉塵轉換。讀競賽帳本裡 `capital_flow` 的 `dust_convert_out`／`dust_convert_in`（只算 LIVE、不算 `details.test`）、競賽的 `ledger_status.json`，以及 `state/dust_convert_attempt.json`（新增的第二個可讀路徑；沒有這個檔案＝還沒試過，不是錯誤）。`needs_review`、`failed`、`partial`，或 `converting` 超過 30 分鐘沒更新（程式中途掛了、結果不明）都是 `failed`（同一策略日同一狀態只通知一次）；帳本有轉出與轉入列＋狀態 `done`＋轉換後（超過寬限）對帳 `RECONCILED` 才是 `observed`，而且保持 `needs_human`：對照幣安 App 的小額資產轉換紀錄與備註裡的 tranId，只有你能做。對帳 `DIVERGED` 是 `failed`。

## f-70 第二批：A1 穩定天數、f-63、x5、f-38（`a1-stable`、`crypto-one-entry-a-day`、`crypto-stop`、`momentum-halt-notice`）
沒有新增可讀路徑（只讀已在清單內的 `/var/lib/ops-notify/state.json`、加密的 `trading_ledger.jsonl`／`ledger_status.json`／`state/state.json`、動能的 `fleet_event_log.jsonl`）。

- **`a1-stable`（x8、f-63、x5 第三項）**：讀維運通知的讀數檔裡四支策略各 5 個軸（運行狀態＝HEALTHY、帳本與 Google 表＝RECONCILED、匯出檔與服務單元＝OK）＋主機時鐘，全部 `severity` 為 ok 且值正常才算正常。穩定時間沿用第一批的 `_streak`（72 小時、前一個正常輪次超過 45 分鐘就重算），有任何一個讀數不正常也重算。讀數超過 90 分鐘沒更新、或某個對象整個沒有讀數是 `error`（維運通知自己沒在看，不能當通過）。**只涵蓋維運通知看的項目**：資金費同步每 4 小時 exit 0、停損價與停損單不變，程式沒讀，結案前我另外到主機查（通知文字會寫明）。
- **`crypto-one-entry-a-day`（f-63）**：A1 加密帳本 2026-10-23 台北 16:22（重開）之後 `source=entry_signal`、LIVE 的 `trade_open`，按 UTC 日分組；同一個 UTC 日有兩個不同 `trade_id` 的進場立刻 `failed`（同一筆交易的加碼不算）。可結案的條件：重開後有進場，且那一天（UTC）已結束、當天只進場一次——代表策略帶著修法活過一次 UTC 午夜。證據行會寫那幾天有沒有出場；「出場後同一天再進場」這個真正出過事的情形沒測到時會明說。
- **`crypto-stop`（x5 前兩項）**：停損觸發＝重開後 LIVE 的 `trade_close` 且 `source` 以 `native_stop` 開頭，要等其後（超過寬限）的帳本對交易所對帳 `RECONCILED` 才算看到，`DIVERGED` 是 `failed`；移動停損沿用開發機 x5b 的判斷（`_follow_stop`，從 x5b 檢查抽出，行為不變）：同一筆交易兩輪之間停損單號換新且價格收緊（空單往下、多單往上）。**永遠不可結案（`needs_human`）**：撤舊再掛「沒有空窗」從這些檔案看不出來，結案時我到交易所查。兩輪（30 分鐘）之間移動又平倉會看漏。
- **`momentum-halt-notice`（f-38）**：A1 動能的真實（非測試）R3 事件，量 `recorded_at` 到維運通知的 `delivered` 時間（上限 15 分鐘＝匯出計時器 1 分鐘＋輪詢 10 分鐘＋餘裕），並看動能的匯出檔軸是 OK（刷新計時器壞掉會讓它變過期）；超過時間、第二則欠送超過 70 分鐘、匯出檔軸不正常都是 `failed`。匯出檔本身的修改時間沒有讀，用送達延遲推定「約一分鐘內更新」，證據行會寫明。與 `safe-halt-notice`（f-35／f-37）看同一類事件，同一則動能 R3 事件可能各傳一則通知（涵蓋的項目不同）。

## 開發機加密策略的 x5b 測試網檢查（`dev-crypto-x5b`，phase-x5b）
x5b 剩下三件事要等開發機加密策略**自己**出訊號才驗得到（乾淨接手、停損真的觸發、移動停損撤舊再掛）。這個檢查只負責「看到」，不結案：

- **進場**：開發機帳本在 `2026-10-18 08:00 UTC`（手動重複送單測試之後）之後，有 `source=entry_signal`、`execution_mode=DEMO` 的 `trade_open`。手動測試列（`x5b_test`）、接手列、舊交易、真倉都不算。看到時發一則「可以開始 x5b 測試」，之後的接手測試要使用者逐項授權。
- **停損移動**：移動不寫進帳本，只能看開發機 `state/state.json` 的 `stop_plan_order_id`：同一個 `trade_id` 在兩輪之間出現新編號，就是撤舊再掛。這個檔案是這次唯一新增的可讀路徑（確切一個）。限制：兩輪（30 分鐘）之間移動又平倉可能看不到。
- **停損觸發**：自己進場的交易，出現 `source` 以 `native_stop` 開頭的 `trade_close`。
- 進場後過了寬限，Google 表對帳仍 `DIVERGED` 時回報失敗。
- 三項都看到時仍是 `observed` ＋ `needs_human`，不會是 `closable`：帳本、Google 表、出場單編號（`mc-t-`）要人（Claude 加使用者授權）逐項查證。

## 裝在新主機（fleet-standby-1，階段 3 切換；P3）
安裝腳本本來就用 `WATCH_USER` 參數化（單元是 `@WATCH_USER@` 範本），新機用 `ubuntu` 即可，不用建 `ai001`：

1. 先裝好三支策略與 ops-notify（腳本要從 `/etc/ops-notify/ops-notify.env` 複製 LINE／Telegram 設定，沒有就失敗）。
2. 在 ubuntu 家目錄放 5 個 clone：`trade-alerts`、`ed-seykota-systematic-trend-following`、`mexc-4h-momentum-trailing-stop`、`my-crypto-bot`、`btc-bull-market-competition`（私有 repo，取碼方式見切換手冊 P1；沒有 clone 時單元會略過，登記冊類檢查會回報錯誤）。
3. `~/.ssh/oci_a1_key`（權限 600；從開發機用 ssh 串流複製，不落地不印出）與 A1 的 known_hosts（`ssh-keyscan -t ed25519 161.33.186.220 >> ~/.ssh/known_hosts` 之後，**與開發機 known_hosts 的指紋核對一致**才算數；程式用 `StrictHostKeyChecking=yes`）。
4. `sudo WATCH_USER=ubuntu bash deploy/observation-watch/install.sh`：開頭的警告式預檢（`watch_preflight.sh`）會列出缺的 clone、known_hosts、金鑰權限，只警告不中止。
5. 搬 `state.json`（保留已 ack／已通知的紀錄，否則第一輪會重複通知）：開發機 `~/.local/state/observation-watch/state.json` → 新機同路徑（擁有者 ubuntu）。
6. `sudo systemctl start observation-watch.service` → `python3 /opt/observation-watch/observation_watch.py report` 看 `檢查時間` 新鮮、`systemctl --failed` 為空。

開發機那一側的檢查讀「本機」檔案（`sudo -n cat`，ubuntu 在新機 sudo 免密即可），所以必須與三支策略同機。
