# 對話串收尾 SOP（交接前檢查）

一個工作對話串要結束前照這份逐項做完，讓下一個人（或下一個 Claude 對話）打開就能接手，不用猜「做到哪、
有沒有東西卡在半路」。用詞一律照 `src/trade_alerts/catalog/fleet-glossary.json`（正式機／開發機、修復機器人…）。

每一項都要**實際跑指令查證**，不能憑記憶勾選——記憶與頁面都可能跟現況脫節（2026-09-18 就發現進度頁有一半內容
只存在資料庫、一個被版本號蓋掉）。

## 1. 程式碼與分支（每個這次動過的 repo 都要做）

```bash
for r in trade-alerts mexc-4h-momentum-trailing-stop ed-seykota-systematic-trend-following my-crypto-bot \
         btc-bull-market-competition ops-notify ops-control portfolio-query; do
  cd ~/$r || continue; git fetch -q --prune origin
  echo "== $r dirty=$(git status --porcelain | wc -l) openPRs=$(gh pr list --state open --json number --jq length)"
  git branch --format='%(refname:short) %(upstream:track)'
done
```

- [ ] 工作目錄乾淨（`dirty=0`）；沒有沒 commit／沒推的東西。
- [ ] 沒有開著的 PR；有的話要嘛合併、要嘛在交接摘要寫清楚為什麼開著、等誰。
- [ ] 本機殘留分支清掉：遠端已刪（`[gone]`）且對應 PR 已合併的，用 `gh pr list --state merged --head <分支>` 確認後
      `git branch -D`。沒有上游、也查不到已合併 PR 的分支**不要刪**，寫進交接摘要。
- [ ] 策略 repo 與維運 repo：分支包含關係成立（一律用 `origin/` 完整名稱，避免撞到本機殘留同名分支）：
      `git merge-base --is-ancestor origin/operations origin/testing && git merge-base --is-ancestor origin/testing origin/development`。
- [ ] 本機 checkout 停在該 repo 的慣用分支、且跟遠端一致（`git status -sb` 沒有 ahead/behind）。

## 2. 審閱歸檔

- [ ] 這次每一個經過 Perplexity 審閱的 PR，都在該 repo `archive/reviews/` 有 `YYYYMMDD-<名稱>.md`（PR、head、base、
      squash commit、審閱結論與輪數、CI run、重點、隔離聲明）＋同名 `.patch`（`git show --format= <squash commit>`）。
- [ ] 純文件豁免的 PR 不用歸檔，但要能在 PR 說明裡看出它是純文件。

## 3. 登記冊與生成頁面（trade-alerts）

```bash
cd ~/trade-alerts
.venv/bin/python -m pytest -q
.venv/bin/python scripts/render_guides.py --check
.venv/bin/python scripts/verify_registry_evidence.py   # 登記冊有改過就要跑
```

- [ ] 三個指令都通過。
- [ ] `recent_changes` 反映**最後一次**登記冊編輯真正改的東西；沒有就設成 `[]`（不能放著上一輪的舊內容）。
- [ ] 一致性登記冊、風險登記冊兩個 Artifact 已用 `main` 上的檔案重新發布到原網址（先 `read` 一次再帶 `url` 發布）。
- [ ] 新增給人看的文字沒有舊叫法（`tests/test_fleet_glossary.py` 會擋 trade-alerts 內的；其他 repo 要人工留意）。

## 4. 機隊工程進度頁

- [ ] 這次有狀態變化的項目都已更新：**先改頁面 ITEMS（改內容就把 `v` 加一）→ 重新發布 → 用同一份內容（含 `v`）
      寫進資料庫**。不要只寫資料庫。
- [ ] 發布後把資料庫 `checklist` 全部讀回來，跟頁面 ITEMS 逐筆比對 `v`：資料庫的 `v` 跟頁面不同就會被靜默忽略。
- [ ] 「建議下一步」（資料庫 `meta/next`＋頁面 `DEFAULT_NEXT`）重新掃過：急迫的先；沒有急迫的就接同一組下一小塊；
      同組做完才換組。理由用白話寫。
- [ ] `meta/info` 的說明與最後更新時間已更新。
- [ ] 新開的關卡／項目用白話寫、每項附建議模型。

## 5. 正式機／開發機現況

- [ ] 這次有部署的，寫下兩台主機現在各跑哪個 commit、哪些開關是開／關。
- [ ] 進行中的觀察期寫明到期時間（絕對日期＋時區），同時記在進度頁與記憶裡。
- [ ] 部署腳本是整支分支重裝：這次如果推過正式機，確認有沒有順帶把「已合併但刻意暫緩」的東西一起帶上去。

## 6. 記憶（Claude 的跨對話記憶）

- [ ] 專案記憶：現況、下一步、日期都是絕對日期；過時的敘述直接改掉，不要只在後面追加矛盾的新段落。
- [ ] 這次使用者糾正過的做法、新定的規則，各寫成一條 feedback 記憶（附 Why／How to apply）。
- [ ] `MEMORY.md` 每條一行、沒有重複、描述跟檔案內容一致。

## 7. 交接摘要（最後一則回覆）

用白話、四段：
1. **這次做完了什麼**（附 PR 連結）。
2. **還開著的事**：觀察期、等使用者決定的事、刻意沒做的事與原因。
3. **建議下一步**（跟進度頁「建議下一步」一致）。
4. **需要使用者動手的事**（例如只能由使用者改的主機設定）。
