# 審閱歸檔：觀察區「AI檢查」項目改自動通知，第一批（PR #304，f-70）

- PR：bcup02/trade-alerts #304；squash `d76ef8f9b6a6520076786bbb3be9a9e7448317f4`（main）
- 審閱：ChatGPT — 首審 BLOCK（head `4fcb4afd4d10281febf80dc60d4da169e2f0e7ed`）→ 複審 PASS（head `343a5232f696f178b8a2f49b6b667b3e2ec7dae1`），共 2 輪；base `54429074c55368033614d1edff9224f4b2e7d248`
- CI：首審 run 40088018206（1469 passed）、複審 run 40088484545（1471 passed）

## 重點
- 新增三個唯讀檢查：`dev-trend-reconcile`（f-7 後半，開發機趨勢對帳回到 RECONCILED）、`health-publish`（f-45，兩台讀數發布單元連續正常 72 小時）、`dust-convert`（f-66，競賽第一次真實粉塵轉換與其結果）；讀取白名單新增 `health-publish-state.json` 與 `state/dust_convert_attempt.json` 兩個單一檔案。
- 門檻預設：穩定 72 小時（`STABLE_STREAK`），可在程式裡改。

## 審閱 BLOCK 與修正
- **BLOCK-304-01**：`health-publish` 的穩定起點存在 `extra.healthy_since`，而 `run_checks()` 讓出錯的那一輪保留舊的 `extra`，所以「正常→讀不到→恢復」會把看不到的空窗算進 72 小時，誤報可結案。修：新增 `extra.last_seen` 與 `STREAK_MAX_GAP`（45 分鐘），前一個看到兩台正常的輪次離這一輪超過 45 分鐘就重新起算；補跨輪回歸、144 輪正常節奏與間隔邊界（30/45/46/120 分鐘、缺 `last_seen`）測試，並反向驗證拿掉間隔規則時新增測試會失敗。
- 教訓：**凡是「連續 N 小時／N 天」的檢查，要把「出錯的輪次不更新 extra 但保留舊值」當成設計前提，用『最近一次看到正常的時間』判斷空窗，並一開始就寫「健康→讀不到→恢復」的跨輪測試**；單測狀態函式與單測「讀不到會出錯」都不足以抓到。第二批（A1 健康穩定天數、f-63、x5、f-38）照此設計。
- 首審另列「未能核對 dust-convert 的 attempt 狀態字串」：複審已對照競賽 operations `9a6b0c9` 的 `src/btc_competition/dust_convert.py` :306–341 確認一致。

## 部署
- 2026-10-24 台北約 19:25 部署到 A1-dev（只換 `/opt/observation-watch/observation_watch.py`，blob 12f73fc→fe68d62，舊檔備份在 ~ubuntu/observation_watch.py.bak-20261024b）；手動跑一輪 `observation-watch.service` 成功（exit 0）；報告含 15 個檢查，三個新檢查都 waiting（趨勢對帳還是 DIVERGED、兩台讀數正常連續 0 小時、尚無真實粉塵轉換）；0 個失敗單元；未碰 A1 正式機。

## 隔離聲明
審閱端只讀 GitHub 的 PR、程式、測試與 CI 日誌；未碰 /opt、/etc、/var/lib、systemd、交易所、Google 或任何實機帳本；未 checkout、未跑測試、未合併或推送。
