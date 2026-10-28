# PR #318 觀察區臨時檢查 dev-competition-drill（R033 P3 開發機演練期間）

- PR：bcup02/trade-alerts #318；base 714d1dc24c3043d264d74c48c366a10c0f2dab6c；squash c565cec03eabea2ba7bb09802bcd76ab7fd0ed98
- 審閱：ChatGPT 1 輪，head c785fb8d2cac26b513b56b85c5c44da1591a74c9 PASS（審閱PR#318結論：PASS）。CI run 40701374771，1573 passed。
- 重點：臨時檢查，讀開發機競賽的 ledger_status／google_reconcile_status／fleet_event_log（三個路徑本來就在白名單），任一對帳 DIVERGED → failed，其餘 waiting，永不可結案；演練結束後移除。
- 審閱者備註（非阻擋）：FAILED 的 key 含兩份對帳的 note，另一份 note 變動也會再通知一次，可接受。
- 實測：演練中被 SIGKILL 的賣單未補記時，偵測程式 22:58（台北）確實傳出失敗通知；補記後回到等待中。
- 部署：只換開發機偵測副本單檔（已做）；不用部署 A1。
- 隔離：審閱端未接觸主機、交易所、帳本。
- 歸檔註記：這個檢查演練結束後會從 CHECKS 移除（另開 PR）。
