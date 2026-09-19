# 審閱歸檔：momentum `ops_export.writer` pending→done；`sources.momentum` 從 `520cb9e` 重新釘選到正式機分支 HEAD `b48b88b`

- **PR**：`bcup02/trade-alerts` #36，head `b5d80c3a344527be85e3a1edbfda178000fa9ded`
- **base**：`main` @ `00d81f4`
- **squash 合併為**：`cc8f84b`
- **審閱者**：Perplexity — **`PASS（一輪）`**
- **CI**：`pytest` = success（run `35353784079`；272 passed（跟 base 一致））
- **部署**：不需要（trade-alerts 是純函式庫／資料＋靜態頁；頁面已重新發布到 Artifact）

## 為什麼做

查證 Phase 5d/6c 時發現：當天資金費同步修復（F3）用整支分支重裝上正式機，順帶把 2026-09-17 已合併、原本暫緩的 6b `repair_bot.py` 與 7b 匯出檔寫入一起帶上去。自動補寫與維運通知轉送兩個開關都沒開，零行為改變；但 `scripts/repair_bot.py:278 refresh_ops_export` 確實每輪在正式機改寫 `audit/ops_export.json`，登記冊仍寫「只在開發機」，故更正。

## 審閱重點

`list_branches` 確認 `b48b88b` 就是正式機分支 HEAD；`scripts/repair_bot.py`、`src/strategy.py` 在新舊 commit 的 blob SHA 相同，證明重新釘選不破壞既有證據行號；`verify_registry_evidence.py` 邏輯上對全部條目重查；判準自洽（無開關、無條件執行的寫檔＝已做；有開關擋住的功能＝未做）。

## 隔離聲明

變更只在 trade-alerts 的 `src/trade_alerts/`、`schemas/`、`scripts/`、`tests/`、`docs/` 範圍；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或正式機帳本，無密鑰。完整差異見同名 `.patch`。
