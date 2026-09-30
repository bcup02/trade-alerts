# 錯誤清單退役兩條 DIVERGED_UNIT_EXIT（f-8）

- PR：[bcup02/trade-alerts#85](https://github.com/bcup02/trade-alerts/pull/85)，head `8cd7515`，squash 合併 `7a229d4`（base `2a2652a`）
- Perplexity：一輪 **PASS**
- CI：pytest 381 passed（run 36658737933）

## 內容

`FLEET.LEDGER_DIVERGED_UNIT_EXIT`（exit 2）、`FLEET.GOOGLE_DIVERGED_UNIT_EXIT`（exit 3）描述的「對帳分歧時故意讓 unit 變紅」
在 Phase 4b 已改成四支都 exit 0 並上正式機，兩條從錯誤清單與一致性登記冊移除、代碼移入 `retired_codes`（永不重用）；
文件補退役說明；兩張產生頁重新產生；`recent_changes` 設為 `[]`，頁面標示測試改為在空清單時用合成的一筆驗證。
帳本／Google 表不一致的偵測與通知不變（ops-notify 兩軸）。不用部署。

## 審閱重點

確認兩個代碼沒有執行期發出點、retired_codes 格式與不可重用不變式成立、v0.23.0 釘選不受影響、產生頁差異（44→42 條、done 22→20）
完全由退役與 recent_changes 清空解釋、改寫的測試不是空轉。

## 隔離聲明

變更只在 catalog／registry JSON、產生頁、`docs/fleet-error-catalog.md` 與兩個測試；未接觸 /opt、/etc、/var/lib、systemd、交易所、
Google 或實機帳本。完整差異見同名 `.patch`。
