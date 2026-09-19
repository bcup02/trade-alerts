# 審閱歸檔：登記冊 JSON 新增 `recent_changes`、頁面加「最新變動」金黃色標示與摘要欄

- **PR**：`bcup02/trade-alerts` #37，head `bce580f1a7e025ef540e04c186f9bfd0eeaaafd5`
- **base**：`main` @ `cc8f84b`
- **squash 合併為**：`6b1a4be`
- **審閱者**：Perplexity — **`PASS（一輪）`**
- **CI**：`pytest` = success（run `35361165144`；276 passed（+4））
- **部署**：不需要（trade-alerts 是純函式庫／資料＋靜態頁；頁面已重新發布到 Artifact）

## 為什麼做

使用者要能一眼看到最近一次更新改了什麼，並用來確認更新有沒有真的生效。`registry_problems` 驗證每筆指到的格子存在且目前是已做／不適用。

## 審閱重點

控制流程逐行核對無漏判；schema 與 Python 檢查一致（Python 更嚴格不矛盾）；空清單＝零 problem；`complete` 分組在覆寫點顏色之前算好，不受影響。

## 隔離聲明

變更只在 trade-alerts 的 `src/trade_alerts/`、`schemas/`、`scripts/`、`tests/`、`docs/` 範圍；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或正式機帳本，無密鑰。完整差異見同名 `.patch`。
