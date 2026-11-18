# PR #383 審閱歸檔：自動更正通知說出 Google 入隊失敗（f-89，v0.30.44）

- PR：bcup02/trade-alerts #383；squash `06594e6`（tag `v0.30.44`）；審閱 AI：ChatGPT；結論：第 1 輪 PASS（head `9ce13fe`，base `559dfca`，CI run 44236140195，1679 passed）。
- 範圍：`unrecorded_fill.py` 新增 `_google_queue_failed`（`google_intent_error` 或 `error` 任一個是非空字串即失敗）與固定句子；交易路徑看 `post`、現貨路徑看 `written`，失敗時通知多一行；5 個測試函式（9 案例）；錯誤目錄 10 處 `sources` 行號搬移（663→677、707→722、737→752，都指 `append_fleet_event(`）；版本 0.30.44。
- 原因：f-88 後續。通知原本不提 Google 更正排隊失敗，使用者可能誤以為 Google 表已對。

## 審閱重點與結論
- 帳本寫入、是否更正的判斷、事件寫入參數與 base 完全一致；唯一新增的是通知文字陣列的條件展開。
- 外部錯誤文字不進通知（固定句子），原文仍在 `details.post`／`details.written`。
- 反向驗證：拿掉程式修改後新測試 4 案例失敗。
- 隔離聲明：審閱者只讀 GitHub PR、repo 檔案與 Actions 日誌，未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或實機帳本。

## 部署
- 本 PR 只合併與打 tag，沒有主機部署；四支策略改釘 v0.30.44 後新通知才生效（各自 PR，上正式機先問使用者）。

## 已知缺口與後續
1. 審閱者建議（非阻擋）：空白字串與非字串 `error` 值可再各補一個參數案例。
2. 補發路徑與 `line_query_published` 沒動。

## 教訓
1. 在檔案中段插入程式會讓錯誤目錄 `sources` 行號全部位移；`test_catalog_sources_in_this_repo_point_at_the_call_that_emits_the_code` 會抓到，搬完要用舊新那一行文字相同確認。
