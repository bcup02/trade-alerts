# 審閱歸檔：補登漏掉的錯誤目錄條目 `SEY.VERIFIED_CLOSE_PROPOSED`（33→34 條）＋登記冊列＋對稱性回歸測試

- **PR**：`bcup02/trade-alerts` #38，head `a599ed62af502d913ab42b862f2449f0835f7f85`
- **base**：`main` @ `6b1a4be`
- **squash 合併為**：`86e45cd`
- **審閱者**：Perplexity — **`PASS（一輪）`**
- **CI**：`pytest` = success（run `35364549269`；277 passed（+1））
- **部署**：不需要（trade-alerts 是純函式庫／資料＋靜態頁；頁面已重新發布到 Artifact）

## 為什麼做

使用者核對進度頁 5b/5c 時在登記冊找不到趨勢策略的修復機器人：它從 2026-09-15 就在正式機寫這個事件，但 v1 目錄從未收錄（文件早已提到、一直沒補）。比照動能策略同名條目處置，兩格皆未做（寫的是 v1 等級標籤 R1）。

## 審閱重點

重建 seykota `scripts/repair_bot_shadow.py` 建立 commit 全文逐行編號，確認第 144 行是 `append_fleet_event(... code=_CODE, risk_tier="R1")`；新舊條目欄位對等由 CI 測試斷言；統計數字重算正確；只動文字未動代碼與分級。

## 隔離聲明

變更只在 trade-alerts 的 `src/trade_alerts/`、`schemas/`、`scripts/`、`tests/`、`docs/` 範圍；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或正式機帳本，無密鑰。完整差異見同名 `.patch`。
