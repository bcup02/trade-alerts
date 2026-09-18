# 審閱歸檔：登記 Binance 資金費同步缺口（v0.20.0 之後，未動版本號）

- **PR**：`bcup02/trade-alerts` #33，head `45b43aa0ba345c0e6785fc9c3ab5e91226157f6a`
- **base**：`main` @ `d08d0fe`
- **squash 合併為**：`047e7e8`
- **審閱者**：Perplexity — **`PASS`**（一輪）
- **CI**：`pytest` = success（run `35338326257`；271 passed，跟 base 一致，無新增測試）
- **部署**：不需要（純資料＋靜態頁，無執行期程式碼變更）

## 這一支做了什麼

修 f-3（`mexc-4h-momentum-trailing-stop#92`，真倉 momentum 資金費同步排程的 bug）過程中查出：momentum 真倉
已於 2026-09-04 切換到 `EXCHANGE=binance`，但負責查資金費的 `scripts/sync_funding_fees.py` 從沒跟著換，
至今還在查 MEXC；順手查了同樣在 Binance 交易的 seykota，發現**整個 repo 沒有任何資金費同步腳本**，而且
已經造成一筆真實漏記（BTCUSDT，2026-09-03T17:31–2026-09-04T02:41，持倉 9.16 小時，跨過 00:00 UTC 結算，
資金費永遠補不回來了）。兩支共用的 `binance-trading-toolkit` 完全沒有查資金費的方法。

登記進 `fleet-rollout-registry.json` 新能力 `reconcile.funding_fee_sync`：momentum／seykota `pending`（新 phase
`binance-funding-sync`，尚未排定，需先幫共用套件加能力）；mycrypto `done`（`sync_funding_fees_entry.py` +
systemd timer，真倉確認運作中）；btc-competition `n/a`（現貨策略，沒有資金費概念）。`docs/guides/
fleet-rollout-register.html` 由 `scripts/render_guides.py` 重新產生。

## 審閱結論：PASS

Schema／`registry_problems()` 規則逐項核對通過；審閱者直接查 GitHub 上 `my-crypto-bot`／
`ed-seykota-systematic-trend-following` 兩個 repo 的真實目錄，確認 mycrypto 的 `done` 證據檔案／systemd
unit 真實存在，seykota 的「完全沒有資金費腳本」也核實為真、非誇大；HTML 與 JSON 內容一致；變更範圍精確
限於宣稱的 2 個檔案；既有 271 條測試數量不變（預期，純登記無新程式邏輯）。

## 隔離聲明

未接觸 `/opt` `/etc` `/var/lib`、systemd、交易所、Google、實機帳本；無 token/密鑰；純資料與文件變更，
無執行期程式碼。
