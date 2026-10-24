# 審閱歸檔：觀察區「AI檢查」項目改自動通知，第二批（PR #306，f-70）

- PR：bcup02/trade-alerts #306；squash `2175004`（main）
- 審閱：ChatGPT — 首審 BLOCK（head `f16572ac306a9287512e60f85d92e5dfa426eb6c`）→ 複審 PASS（head `6953b9c7e42e9621508653ca6d0da7252acc1da6`），共 2 輪；base `08b0364ca48d3fb532dd2f1d0cd130ae7b802ba7`
- CI：首審 run 40089946926（1499 passed）、複審 run 40090664040（1565 passed）

## 重點
- 新增四個唯讀檢查：`a1-stable`（x8／f-63／x5：四支策略各 5 軸＋主機時鐘共 21 個讀數連續正常 72 小時）、`crypto-one-entry-a-day`（f-63：同一 UTC 日只進場一次，進場日結束才可結案）、`crypto-stop`（x5：停損觸發需其後對帳一致、移動停損沿用 x5b 判斷、永不自動結案）、`momentum-halt-notice`（f-38：動能真實 R3 事件到維運通知 ≤15 分鐘、匯出檔軸 ok）。
- 沒有新增可讀路徑。抽出 `_streak`（與 health-publish 共用）與 `_follow_stop`（x5b 的停損單號追蹤，行為不變）。
- 程式不讀的部分照實寫進通知與文件：資金費同步 exit 0、停損價／停損單不變、撤舊再掛有無空窗、匯出檔修改時間（用送達延遲推定）。

## 審閱 BLOCK 與修正
- **BLOCK-306-01**：`_ops_readings` 只確認每個對象至少有一個讀數，目標在但缺部分軸（例如只有 runtime）仍累計健康時間。修：`REQUIRED_READINGS` 明列 21 個，缺任何一個或不是物件即 error。
- **BLOCK-306-02**：`checked_at` 為 None 就跳過新鮮度檢查，任何軸缺時間戳都能繞過。修：只有 `units` 軸（設計上沒有 `checked_at`）在 None 時可略過，其餘缺少／讀不懂／過期（含未來時間）一律 error；units 若帶時間仍要新鮮。
- **f-38 補充風險**：`momentum:export` 的 severity 為 None 時被放行。修：讀數缺少或沒有字串 severity 是 error，不是 ok 是 failed。
- 教訓：**「必要的輸入集合」要寫成明列的常數並逐一驗證，不要用「每個對象至少有一個」或「有值才檢查」這類寬鬆條件；任何『缺了不能算正常』的檢查，第一版就要補『單一必要項缺失』與『時間戳缺失』的測試**。

## 部署
- 2026-10-24 台北約 19:42 部署到 A1-dev（只換 `/opt/observation-watch/observation_watch.py`，blob fe68d62→e5dd652，舊檔備份在 ~ubuntu/observation_watch.py.bak-20261024c）；手動跑一輪 `observation-watch.service` 成功（ExecMainStatus 0）；報告含 19 個檢查，四個新檢查都 waiting（A1 讀數正常連續 0 小時、加密重開後尚無新進場、尚無移動停損或停損觸發、動能尚無真實 R3 事件）；0 個失敗單元；未碰 A1 正式機。

## 隔離聲明
審閱端只讀 GitHub 的 PR、程式、測試與 CI 日誌；未碰 /opt、/etc、/var/lib、systemd、交易所、Google 或任何實機帳本；未 checkout、未跑測試、未合併或推送。
