# 審閱歸檔：分級 v2 W2 共用修復執行器（trade-alerts v0.21.0）

- **PR**：`bcup02/trade-alerts` #47，head `632daf668ce32c5aaa6dfacaf87c94b57a8ff2f5`
- **base**：`main` @ `9a833b1`
- **squash 合併為**：`f147196`，tag `v0.21.0`
- **審閱者**：Perplexity — **`PASS（一輪）`**
- **CI**：`pytest` = success（run `35754525127`；342 passed（287 → +55））
- **部署**：不需要（純函式庫＋目錄資料）。momentum（v2-W3）、seykota（v2-W4）重新釘選時才生效。

## 為什麼做

分級 v2 計畫 W2：momentum `repair_bot.py` 與 seykota `repair_bot_shadow.py` 兩份複製改由共用 `trade_alerts.repair_runner` 取代。開工前讀文件多抓到兩個 seykota 問題（加碼交易永遠補不起來、做空平倉被擋），使用者拍板 A（加碼合併一起修）／B（查交易所失敗算失敗）／C（執行器不推播，只走 ops_export）。

## 審閱重點與結論

六項全 PASS：帳本寫入（staging→行數核對→原子追加，任何失敗 R3、真帳本零改動；一輪最多一次寫入）；損益以交易所為準（只在交易所有回報且差額 > 0.01 時觸發、四個損益欄位一致、容忍內與 v0.20.0 逐欄相同、手動與自動路徑相同）；升格計數（第 3 次才通知一次、之後靜默、升格後轉 R3 為 SUPERSEDED）；加碼合併與做空方向；隔離；回歸。

兩個非阻斷提醒，合併前已查證：
1. 真帳本追加中途失敗的保證依賴既有 `atomic_ledger_append`——該模組已有「寫完讀回核對、不符即拋錯」測試（`tests/test_atomic_ledger_append.py::test_raises_when_the_file_changes_between_write_and_read_back`）。
2. 移除 `assess_auto_repair`／`render_repair_proposal_text` 對外部消費者的影響——四支策略 operations 分支釘選 v0.18.0／v0.16.0／v0.15.0／v0.15.0，只有 momentum `scripts/repair_bot.py` 與 seykota `scripts/repair_bot_shadow.py` 引用，W3／W4 會一併改寫。

審閱者註記：GitHub 連接器讀 `docs/perplexity-review-sop.md` 時只回中繼資料、沒有內文，改依送審信中描述的格式出報告。

## 隔離聲明

變更只在 trade-alerts 的 `src/`、`tests/`、`docs/`、目錄 JSON；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或正式機帳本，無密鑰。完整差異見同名 `.patch`。
