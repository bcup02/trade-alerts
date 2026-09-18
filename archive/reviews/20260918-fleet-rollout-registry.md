# 審閱歸檔：機隊一致性登記冊＋兩頁由 JSON 產生（W1b，v0.20.0）

- **PR**：`bcup02/trade-alerts` #31，最終 head `c4abce72fc8336b860f8743d798f8cc7509124f6`（首審 head `b46a3ff`）
- **base**：`main` @ `6d917c7`
- **squash 合併為**：`6e3876f`，tag `v0.20.0`
- **審閱者**：Perplexity — 首審 **`BLOCK`** → 修正 `c4abce7` → 複審 **`PASS`**
- **CI**：`pytest` = success（首審 run `35312593826` 262 passed；複審 run `35321600739` 271 passed；baseline 232）
- **部署**：不需要（純函式庫＋資料＋靜態頁；目前沒有策略讀登記冊）
- **計畫**：`~/.claude/plans/r0-r4-r1-r2-r3-r4-r2-r3-r1-r2-r3-r1-zazzy-bear.md` 的 W1（後半）

## 這一支做了什麼

- `src/trade_alerts/catalog/fleet-rollout-registry.json`（隨套件發佈）＋ schema：12 項機隊功能 × 四支策略，以及錯誤目錄 33 條
  的「行為」與「寫進事件日誌」在所屬策略的狀態：done（附證據）／pending（附登記過的 phase＋理由）／n/a（附理由）。
- `trade_alerts.rollout_registry`：`load_rollout_registry`、`registry_problems`（規則的可執行版）、`project_rows`。
- `scripts/render_guides.py`：兩個給人看的頁面由 JSON 產生，CI 比對，不可手改。
- `scripts/verify_registry_evidence.py`：跨 repo 證據檢查（手動，不在 CI）。
- 頁面在無頭 Chromium（1280／400px × 淺／深色）實測；實測修掉中文字型備援、說明誤用程式碼樣式、篩選數字語意不一致三處。

## 首審 BLOCK 與修正

**BLOCK 理由**：momentum 的 `repair_bot.pause_brake`（done，`scripts/repair_bot.py:90`）與 `MOM.VERIFIED_CLOSE_REPAIR_BLOCKED`
behaviour（done，`:153`）引用的檔案在 momentum `main` 上不存在；另有兩格理由以同一檔案為前提。

**開發端查證**：檔案存在於 `development`／`testing`（Phase 6b #88，只部署到測試機），但真倉部署來源 `operations`
（`520cb9e`）與 `main` 都沒有；真倉只有 Phase 5 影子版 `scripts/repair_bot_shadow.py`。根因是**登記冊沒有規定 done 以
哪個分支為準**，種子把「只在測試機」的東西算成已做。

**修正（`c4abce7`）**：
1. 新增必填 `sources`（每支策略 repo、`operations`、40 碼 commit），done＝該 commit 上已存在；schema 與 `registry_problems` 強制。
2. momentum 6 格照實改為 pending 或改寫理由（`pause_brake`、`REPAIR_BLOCKED` behaviour → pending v2-W3 等）。
3. 另外 21 個 done 格原本沒有可查證的檔案引用，全部改成 sources commit 上的「檔案:行號」。
4. 新 `verify_registry_evidence.py`；把原本錯誤的格子放回去會失敗（exists on development only）。
5. 測試 +9（sources 各規則反例、引用解析、每個 done 都引用檔案）。

## 複審結論：PASS

差異範圍 10 個檔案與宣稱一致；四個 sources commit 等於各 repo 目前 `operations` HEAD；
`repair_bot.py` 在 operations 不存在、development 存在、`repair_bot_shadow.py` 在 operations 存在（獨立核實）；
分支鎖定規則有反例測試命中；既有 30 條測試零刪除、零改弱。

**審閱者註記的殘留缺口**：連接器只回 blob SHA、不回檔案內容，所以只核到「檔案存在＋commit 一致」，沒辦法逐字核對行號內容。
**開發端補做**：合併後在 `6e3876f` 上重跑 `verify_registry_evidence.py`（四個 repo 已 fetch，operations 仍為
`0213a01`／`520cb9e`／`1efbdc0`／`b8eda43`），結果 0 problems；每個有行號的 done 證據實際指到的那一行如下（逐條人工看過，
momentum `strategy.py:1067` 是 `_protection_unverified_halt` 內 `code="PROTECTION_UNVERIFIED"` 的 latch，btc `runner.py:347`
的 latch 在 `book_corrupt` 時帶 `BOOK_CORRUPT_NEGATIVE_BALANCE`，四支對帳程式 `main` 的 docstring 都寫明 Phase 4b 起每種判定 exit 0）：

- capability latch.unified_model / momentum: src/strategy.py:1067 -> latch = build_safe_halt(
- capability latch.unified_model / seykota: src/seykota_bot/bot.py:386 -> latch = build_safe_halt(code=code, reason=message, evidence=evidence, details=payload)
- capability latch.unified_model / btc-competition: src/btc_competition/runner.py:347 -> st.safe_halt = build_safe_halt(
- capability latch.consecutive_failure_counter / seykota: src/seykota_bot/bot.py:123 -> # Phase 4d consecutive-failure counters -- see
- capability runtime.status_snapshot / mycrypto: portfolio_snapshot_adapter.py:75 -> def _runtime_status(heartbeat: dict[str, Any] | None, *, now: datetime) -> str:
- capability reconcile.ledger_status / mycrypto: reconcile_compare.py:101 -> def main() -> None:
- capability reconcile.google_status / mycrypto: google_reconcile.py:135 -> def main() -> None:
- SEY.PROTECTION_PLACEMENT_FAILED_FLATTENED behaviour / seykota: src/seykota_bot/bot.py:399 -> def _clear_automatic_safe_halt(self) -> bool:
- SEY.PROTECTION_PLACEMENT_FAILED_EXPOSED behaviour / seykota: src/seykota_bot/bot.py:671 -> "PROTECTION_PLACEMENT_FAILED_EXPOSED",
- SEY.PROTECTION_UNVERIFIED behaviour / seykota: src/seykota_bot/bot.py:883 -> "PROTECTION_UNVERIFIED",
- SEY.POSITION_AMBIGUOUS behaviour / seykota: src/seykota_bot/bot.py:1035 -> "POSITION_AMBIGUOUS",
- SEY.RECONCILE_FAILED behaviour / seykota: src/seykota_bot/bot.py:123 -> # Phase 4d consecutive-failure counters -- see
- SEY.RUNTIME_CYCLE_FAILED behaviour / seykota: src/seykota_bot/bot.py:123 -> # Phase 4d consecutive-failure counters -- see
- SEY.CLOSE_FILL_PENDING behaviour / seykota: src/seykota_bot/bot.py:1227 -> "CLOSE_FILL_PENDING",
- SEY.TRADE_EXIT behaviour / seykota: src/seykota_bot/bot.py:1262 -> # Catalog: SEY.TRADE_EXIT (R0).
- SEY.ENTRY_SKIPPED_MIN_CAPITAL behaviour / seykota: src/seykota_bot/bot.py:1342 -> # handling.  Catalog: SEY.ENTRY_SKIPPED_MIN_CAPITAL (R0).
- MOM.PROTECTION_UNVERIFIED behaviour / momentum: src/strategy.py:1067 -> latch = build_safe_halt(
- MOM.STATE_REPAIRED_SAFE_HALT behaviour / momentum: src/safe_halt_state_repair.py:148 -> state["safe_halt"] = build_safe_halt(
- BTC.BOOK_CORRUPT_NEGATIVE_BALANCE behaviour / btc-competition: src/btc_competition/runner.py:347 -> st.safe_halt = build_safe_halt(
- MYC.RECONCILE_DELTA_EXCEEDED behaviour / mycrypto: mexc_futures_bot.py:713 -> append_fleet_event(
- MYC.RECONCILE_DELTA_EXCEEDED emits_event / mycrypto: mexc_futures_bot.py:713 -> append_fleet_event(
- MYC.PROTECTION_PLACEMENT_REJECTED behaviour / mycrypto: mexc_futures_bot.py:1304 -> "PROTECTION_PLACEMENT_REJECTED", "開倉停損單掛失敗，部位可能沒有交易所端保護，請立即手動檢查",
- MYC.PROTECTION_PLACEMENT_ERROR behaviour / mycrypto: mexc_futures_bot.py:1317 -> "PROTECTION_PLACEMENT_ERROR", "掛原生停損單時發生例外，部位本身已開，請務必手動檢查停損狀態",
- FLEET.LEDGER_DIVERGED_UNIT_EXIT behaviour / momentum: src/reconcile_compare.py:107 -> def main() -> None:
- FLEET.LEDGER_DIVERGED_UNIT_EXIT behaviour / seykota: src/seykota_bot/reconcile/compare.py:250 -> def main() -> None:
- FLEET.LEDGER_DIVERGED_UNIT_EXIT behaviour / mycrypto: reconcile_compare.py:101 -> def main() -> None:
- FLEET.LEDGER_DIVERGED_UNIT_EXIT behaviour / btc-competition: src/btc_competition/reconcile_compare.py:228 -> def main() -> None:
- FLEET.GOOGLE_DIVERGED_UNIT_EXIT behaviour / momentum: src/google_reconcile.py:135 -> def main() -> None:
- FLEET.GOOGLE_DIVERGED_UNIT_EXIT behaviour / seykota: src/seykota_bot/reconcile/google_reconcile.py:137 -> def main() -> None:
- FLEET.GOOGLE_DIVERGED_UNIT_EXIT behaviour / mycrypto: google_reconcile.py:135 -> def main() -> None:
- FLEET.GOOGLE_DIVERGED_UNIT_EXIT behaviour / btc-competition: src/btc_competition/reconcile_google.py:283 -> def main() -> None:

**已知取捨**：CI 只保證登記冊結構正確；證據真假靠送審前手動執行 `verify_registry_evidence.py`（讀私有 repo，不放進 CI）。
策略 repo 之後以 `project_rows()` 在各自 CI 自我檢查（計畫 W3/W4），會把這一層收緊。

## 隔離聲明

未接觸 `/opt` `/etc` `/var/lib`、systemd、交易所、Google、實機帳本；無 token/密鑰；未觸發部署。
（首審時為了確認真倉跑哪個版本，唯讀 `ssh trading-main ls` 過 momentum 的 scripts 目錄。）
