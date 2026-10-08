# 審閱歸檔：trade-alerts #149（f-26a：資金費同步寫不進 Google 表的「帳戶餘額總表」分頁）

- PR：bcup02/trade-alerts#149
- 最後審閱的 head：`e3ff6315dd1d8938023ca2dae85179c31a42bd4e`；base：`2bd229037556954b62703bea9bcb969c0780a3bc`（main）
- squash 合併 commit：`25965ca0faee163299c447ac7a33c42a6c45fed4`
- 審閱輪數與結論：2 輪：首審 PASS（舊內容，已作廢）、複審 PASS（新內容）（外部審閱）
- CI（審閱的 head）：run 37798994840（701 passed）
- 專屬錯誤編號：ERR-057／058／059（trade-alerts v0.29.0，bcup02/trade-alerts#149）

## 背景
2026-10-07 使用者把 Google 表的「帳戶餘額總表」分頁 B 欄改成策略中文名後，資金費同步仍用英文專案名比對，接收端每次回 `key_value not found`，只記警告、結束碼照常 0，累計資金費約一天沒更新、沒人發現（f-26）。

## 重點
- 預設專案名改策略中文名；A1 上沒有 `SHEETS_SUMMARY_PROJECT_NAME` 覆寫（唯讀確認）。
- 接收端明確拒絕立刻放棄、連線類連續 3 次才放棄；放棄後每次執行維持結束碼 3，直到寫入確認成功且狀態歸零；格式不對／存不下來／歸零失敗／拿不到鎖都直接結束碼 3。
- 變更檔：src/trade_alerts/catalog/fleet-error-catalog-v2.json、fleet-rollout-registry.json、docs/fleet-error-catalog.md、docs/consumer-release-runbook.md、版本 0.29.0、兩張登記冊頁面。
- 審閱過程抓到的真問題（逐輪）：成功歸零失敗被吞掉、計數檔格式未驗證、日誌含原始例外與接收端回覆（加密）、加密 100 秒不是硬上限、放棄後換錯誤類型回 exit 0、事件旗標存檔失敗造成重複事件、已持久化事件編號被丟掉、事件日誌讀不了被當成不存在、查找與追加無互斥、第一次存檔失敗後回 exit 0、記號恢復產生第二個事件身份、拿不到鎖仍改共用狀態、記號損毀時另造事件身份。修正方式見 PR 對話與各輪審閱回覆。
- 已聲明的限制：audit 目錄完全寫不進去（連 `.unsaved` 記號都寫不了）時沒有東西能跨輪記住，每輪存不下來的執行仍結束碼 3，儲存恢復後重新計數；加密沒有「非 LIVE 不發布」閘門（使用者 2026-10-08 決定，行為與 f-26a 之前相同）；事件到手機這一段（匯出器與維運通知）尚未實機驗證，要等開發機部署。

## 隔離聲明
審閱端只讀 GitHub（PR、diff、check、sticky 摘要），未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 實機帳本、A1 或真憑證；未 push、合併、部署。開發端的單元測試皆為 mock，未連線。
