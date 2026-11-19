# PR #400 審閱歸檔：登記冊——停用策略改成資料（lifecycle），觀察區略過已停用策略（v0.30.49）

- PR：bcup02/trade-alerts #400；squash `588c5a6`；審閱 AI：ChatGPT；結論：第 1 輪 BLOCK（head `5e50336`，base `32e4ca6`）、第 2 輪 PASS（head `5351cbc`，CI run 44469536526，1709 passed）；tag `v0.30.49`。
- 範圍：登記冊新增頂層 `lifecycle`（目前只有 `seykota`＝retired）；`rollout_registry` 由資料推導 ACTIVE／RETIRED；觀察區 registry-drift、registry-awaits 略過已停用策略並在摘要揭露。日後動能被取代只要在登記冊加一筆，不用改偵測程式。

## BLOCK-400-01（已修）
觀察腳本一開始只看 `state == retired` 就略過，`{"momentum": {"state": "retired"}}`（沒日期、沒理由）也能關掉該策略的監控。第 2 輪腳本逐筆驗證（專案已知、state、真實日期 since、reason 非空且 ≤450 字、至少一支策略維持運作），`_load_registry` 讀到不合格的 lifecycle 直接 raise，兩個登記冊檢查都 fail closed。

## BLOCK-400-02（已修）
registry-awaits 略過已停用策略的格子卻沒說明，看起來像「沒有這類格子」。第 2 輪所有回傳路徑都附「已停用、不比對：<專案>」，沒略過時不加註記；測試鎖三條路徑。

## 部署後驗證
開發機 `/opt/observation-watch/observation_watch.py` 換成新版後，phase-sync4 由「舊趨勢策略 24 個檔案漂移」變成「95 個檔案一致（已停用、不比對：seykota）」。

## 教訓
1. 「略過／豁免」類的資料驅動開關，必須把開關本身的格式驗證做成 fail closed，並且在輸出裡說出略過了什麼；否則半套的聲明會靜默關掉監控。
2. 移動 A1 部署複本前，先確認偵測讀的是哪個目錄、比對什麼；這次就是部署流星版把舊趨勢複本移走造成漂移。
