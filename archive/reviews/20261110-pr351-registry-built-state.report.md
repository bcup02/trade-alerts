# PR #351 審閱歸檔：登記冊新增「已完成、尚未上線」狀態（v0.30.30）

- PR：bcup02/trade-alerts #351；squash `b535238`；tag `v0.30.30`；審閱 AI：ChatGPT；結論：首審 BLOCK（351-01／02）→ 複審 PASS（head `6f915023`，CI run 42648952777，1629 passed）
- 範圍：登記冊第四種格子狀態 `built`（程式已寫好合併到開發分支、尚未上正式機；要 evidence 與 phase，不可帶 reason／limit／verified_at，可帶 awaits_commit）；一致性登記冊分未完成／已完成未上線／已完成三類；證據檢查與觀察區 `registry-awaits` 認得 built；V11 的 109 格由未做改 built，仍是未做的 10 格；名詞對照表 status.built；schema；pyproject 0.30.30。順帶修 `_combined`：只有已做與不適用混合時不再誤判未做。
- 審閱 351-01：三格（latch.unified_model、repair_bot.pause_brake、notify.error_id）理由已說程式寫好卻留在未做；改 built，並新增「未做格若說程式已在開發分支就必須寫出還缺什麼」與「V11 剩餘未做逐格點名」測試。351-02：頁面開頭還寫「只在開發主幹的一律算未做」，改成三類說明並加回歸測試。非阻斷建議：orders.step_rounding_decimal 證據改引守門測試與 floor_step（已做）；pending 理由檢查是關鍵字比對、不保證語意充分。
- 沒做（後續）：命名統一（V11＝趨勢策略）與拿掉舊趨勢欄；剩下 10 格未做（Google 對帳等）；已完成未上線的格子上正式機並查證後才改已做。

## 教訓
分類資料時我的轉換規則漏了三格，PR 說明的格數（10）也沒有對照實際（13）。轉換完要用程式把「仍是未做」逐格列出來，和說明逐格比對；有規則就把剩餘清單寫成測試鎖住。
