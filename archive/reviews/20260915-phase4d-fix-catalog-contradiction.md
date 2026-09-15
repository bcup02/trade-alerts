# 審閱歸檔：resolve §4.4 internal contradiction on the consecutive-failure counter's scope

- **PR**：`bcup02/trade-alerts` #18
- **feature 分支**：`phase4d-fix-catalog-contradiction`，head `8b895c5b86eac9f9fe745a52383b41f4c8604347`
- **base**：`main` @ `3670452`
- **squash 合併為**：`1e56e48`（`gh pr merge --squash --delete-branch`）
- **審閱者**：Perplexity — **結論 `PASS`**（連結器直讀，一輪）
- **CI**：`pytest` = success（161 passed，baseline 161，delta 0——純文字修正）
- **對應 patch**：`20260915-phase4d-fix-catalog-contradiction.patch`
- **部署**：不需要（trade-alerts 是純函式庫，無執行期足跡）

## 背景

ed-seykota Phase 4d（seykota 連續失敗計數器）開工前的前置修正。`docs/fleet-error-catalog.md`
§4.4 的文字說「計數器只管 catch-all（`SEY.RUNTIME_CYCLE_FAILED`），其餘八個原因碼不受影響」，
但 `catalog/fleet-error-catalog-v1.json` 裡 `SEY.RECONCILE_FAILED` 自己的 `auto_action` 卻已經
寫著同一套計數器語言（「連續 N 次（預設 3）同類失敗才 latch」），而且它的 `rationale` 明確點名
2026-09-11 的 venv 競態事故就是從這個 latch 點炸的——單次失敗停真倉策略的代價跟 catch-all 的
論證完全一樣。使用者拍板：計數器範圍是兩碼（catch-all + `RECONCILE_FAILED`）各自獨立計數，不是
只有 catch-all。

## 這一支做了什麼

1. `docs/fleet-error-catalog.md` §4.4：標題加註「2026-09-15 修正」；把「其餘八個原因碼...不受
   計數器影響」改成「其餘七個」，新增一段明講 `RECONCILE_FAILED` 額外套用同一套計數器（各自獨立
   計數），並附上矛盾來源與修正依據的簡短說明。
2. `catalog/fleet-error-catalog-v1.json`：
   - `SEY.RECONCILE_FAILED` 的 `auto_action` 拿掉一句「latch 後逾時自動重試一次完整對帳」——
     這是 Phase 6/7（逾時自動執行）才有的行為，提前寫進 Phase 4 的條目裡是範圍錯置。
   - `SEY.RUNTIME_CYCLE_FAILED` 的 `rationale` 把「其他八個原因碼...不受計數器影響」改成
     「其他七個...；`SEY.RECONCILE_FAILED` 額外套用同一套計數器邏輯（各自獨立計數，見該條目）」。
3. **刻意不改**：`schemas/fleet-error-catalog-v1.schema.json`（形狀沒變）、
   `tests/test_fleet_error_catalog.py`（沒有不變式檢查這兩段文字內容）、其餘 9 個 seykota 條目。

## Perplexity 審閱（一輪 PASS）

連結器直接讀取（bcup02 個人帳號，不受 org OAuth 限制）。逐項核對：範圍僅 2 檔案、無 schema/測試
變更、§4.4 與兩個 JSON 條目在計數器適用範圍上完全一致（「其餘七個」在數量上自洽，沒有 off-by-one）、
repository-wide 搜尋確認被移除的越界句子只出現在唯一一處且已清除、JSON 格式合法、§4 全段掃描未
發現其他矛盾。**隔離聲明**：僅讀取 PR metadata/diff/CI，未接觸 `/opt` `/etc` `/var/lib`、systemd、
交易所、Google、實機帳本，未寫入任何內容。

## 依賴關係

`AI-for-column/ed-seykota-systematic-trend-following` #56（Phase 4d 實際程式碼改動）在背景裡
引用了這份文件修正後的規格；兩支 PR 送審時互相參照，但沒有版本 pin 依賴——ed-seykota 的
`trade-alerts` pin 仍是 v0.15.0（Phase 4a 的標籤），這次的 catalog 修正沒有配套切新版本標籤，
因為它是描述性文件、沒有任何執行期程式碼讀取它。
