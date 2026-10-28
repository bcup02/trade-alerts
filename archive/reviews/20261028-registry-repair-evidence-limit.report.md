# PR #313 登記冊：修復機器人取證據在 Binance 超過 7 天查不到成交——補限制說明（v0.30.22）

- PR：bcup02/trade-alerts #313；base 23a78e25af53f33d03cff76a25c3b1d28de190a1；squash cc84de149224026bd140dd8bf0453ee5d0a47f23
- 審閱：ChatGPT 1 輪，head a41cd0ab26363dd72c5f04eac74833bda6e1526c PASS（審閱PR#313結論：PASS）。CI run 40660889172，1570 passed（只改資料）。
- 重點：repair_bot.verified_close 動能／趨勢／加密三格維持 done，補 limit（動能＝A1 實測補寫在 Binance 上從沒成功過；趨勢＝從正式機分支程式確認、尚未 A1 實測；加密＝原限制句後接同樣說明）與動能／趨勢的 verified_at；recent_changes 三筆；版本 0.30.22。
- 審閱者備註（非阻擋）：趨勢的 verified_at=2026-10-28 是程式核對日不是真倉補寫成功日，日後標「A1 實際補寫已驗證」必須有正式機實測證據；recent_changes 是更新滾動展示項目，不是永久變更歷史。
- 部署：不用部署（資料）。
- 隔離：審閱端未接觸主機、交易所、帳本；未動任何 .py。
- 歸檔註記：patch 不含 docs/guides 的產生頁面。
