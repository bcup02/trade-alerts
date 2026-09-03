# trade-alerts — projection receiver config errors are retryable (v0.13.2)

- **PR**：bcup02/trade-alerts #7 → squash `09100e8`（base `519d6c3`）
- **Tag**：`v0.13.2`
- **CI**：pytest 112 → 113；node 綠
- **Perplexity**：審閱結論 **PASS**（無保留）
- **計畫**：`~/.claude/plans/dazzling-enchanting-zephyr.md` 復原 R1

## 事故 + 修正

momentum 首次啟用 v2 drain：部署中的共用 Apps Script Web App 是舊版（v9 @
2026-08-31），`routeRequest` 把帶 `schema_version=google-ledger-projection-v2`
的 v2 payload 送去 legacy `SHARED_SECRET` 檢查 → `{ok:false,error:"unauthorized"}`。
`deliver_projection_v2` 把每種 `ok:false` 都當終端 `REJECTED` → `outstanding_projection_intents`
永久濾掉 + `enqueue_projection_intent` intent-key 去重 → **26 筆積壓意圖一次全被燒掉、無法重排**。

修：`_TERMINAL_RECEIVER_ERRORS = {provenance_invalid, open_projection_invalid,
close_projection_invalid}`（payload 結構壞、重試無意義）才 `REJECTED`；其餘
（unauthorized / signature_invalid / source_not_allowed / unsupported_action /
request_not_fresh / sheet_not_found / malformed / 未知）= 設定/部署問題、同一筆
意圖修好後可成功 → `TRANSPORT_FAILED`，durable outbox 保留。`receiver_row_invalid`
+ 迴圈前 local 檢查仍 REJECTED。

## 消費端

- momentum：pin bump v0.13.1 → v0.13.2（R2 PR 一起）+ `reset_google_projection_outbox.py`
  清掉那 26 筆的終端 dispatch 記錄使其重新 outstanding。
- seykota：Phase C 直接鎖 v0.13.2。
