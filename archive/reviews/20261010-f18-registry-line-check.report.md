# Perplexity 審閱歸檔 — 登記冊檢查腳本：換 sources 提交時比對引用行文字（PR #156，f-18）

- **Repo**：bcup02/trade-alerts
- **PR**：#156，最終 head `b89a8607e5ef9fe32067bbb23b58363f265887c7`，base `fceaeaf4610bc0e4399903dde3548a8957ae6171`（main），squash 合併為 `50bbb60`
- **審閱者**：Perplexity — 五輪：`5378d1c` **BLOCK** → `94b5abb` **BLOCK** → `32a50b3` **BLOCK** → `0ad8d21` **BLOCK** → `b89a860` **PASS**
- **CI**：pytest = success（最終 run `38033852728`；801 passed，baseline 763，+38）。不需要部署、不發 tag（只動 scripts／tests／README／SOP，沒有版本變動）

## 做了什麼

`scripts/verify_registry_evidence.py` 原本只確認「引用的那一行存在」。2026-09-26 與 2026-10-04（#113）兩次，登記冊換 `sources` 提交後 108 處 file:line 引用指到別的程式，腳本仍顯示 0 problem。新增與基準登記冊（`--against`，預設 `origin/main`）的比對：舊提交舊行號那一行要等於新提交新行號那一行，而且在同一個函式（`ast`）。

- 配對：整格引用依位置，只有新舊兩格引用的檔案數量與順序完全相同才配對，否則整格 `unpaired`。
- `shifted`（舊那行在兩邊同函式各只有一處、引用沒指到它）一律失敗；`changed`（改寫、刪除、搬函式、同名定義／多行 lambda、同函式相同文字且搬動過、檔案讀不到或無法解析、行號 0）失敗並印出新舊兩行，人讀過才可 `--accept-changed`；`unpaired` 須 `--accept-unpaired`。
- `--relocate` 只處理 `shifted`，兩邊唯一才移動、沒移動不寫檔；`--no-compare` 略過。行號只用 `\n` 切（含 U+2028／換頁字元的檔案行數比以前少，相容性例外已寫進說明與測試）。

回測 #113：首審 BLOCK 版（b28613b）對基準 19f3ea9 比對 139 處，97 shifted、12 changed、8 格 unpaired，`--relocate` 修掉 97 處；複審 PASS 版（bdd6a3a）135 處，1 shifted、10 changed、12 格 unpaired——那 1 處 shifted 是 #113 通過審閱後仍留在 main 上的真錯（趨勢 `latch.restart_only_clear` 理由引用 `safe_halt_resume.py:103`，實際 :134），由 f-27 修。

## 審閱過程（四次 BLOCK，每次都是真漏洞）

1. 首審：`_scope()` 靠縮排（不同 class 同名方法放過、巢狀函式結束後判錯、多行簽章與 decorator 變 `<module>`）；引用個數變動讓整格 `rewritten` 不比對；舊提交讀不到卻成功；`--relocate` 在「兩處相同文字減為一處」時改到另一個分支、沒移動也寫檔。→ 改用 `ast`；`unpaired` 預設失敗；讀不到歸 `changed`；relocate 要兩邊唯一、沒移動不寫檔。
2. 第二輪：我的「依內容配對」會把兩個不同用途的引用交叉配對、`--relocate` 寫成互換還顯示 0 problem；同名巢狀函式與多行 lambda 被當成同一個範圍；已落在另一個重複行的引用被放過。→ 取消內容配對；重複名稱與 lambda 標 `#dup` 歸 `changed`；補序號規則。
3. 第三輪：按檔分組配對讓跨檔互換看起來乾淨；序號規則在分支重排後指到另一個分支。→ 整格檔案順序必須相同；重複行加上一行／標頭鏈。
4. 第四輪：`_identity()` 用縮排回溯找「區塊標頭」，多行條件 `if (\n buy\n):` 會抓到 `):`，漏掉真正的條件。→ **整個拿掉**，不再用上下文猜身分：同函式相同文字只有「行號沒變且上面的檔案內容完全沒變」才通過，其餘 `changed` 交人。
5. 第五輪 PASS：審閱者確認 R4-1 路徑已移除、前綴相同例外在本工具的文字位置契約下可驗證（`#dup`、lambda 仍先進 `changed`）、被刪的四個 `_identity` 測試編碼的正是不安全規則、新測試等價或更強。

## 審閱者標明的界限

- PASS 只表示程式變更可進入合併程序，不是部署授權；這支工具不宣稱 Python 語意等價，單行文字比對仍有既定限制。
- 全量回歸採 GitHub Actions 原始日誌（801 passed），審閱者沒有在本機 checkout 重跑。
- 非 Python 檔只比對行文字與位置規則，不代表理解設定檔區塊語意。

## 教訓

- 比對「身分」的啟發式規則（依內容配對、序號、上下文）每一條都被找到新繞法；最後留下來的只有「可證明的」規則（兩邊唯一；行號與前綴都沒變），其餘交給人。以後這類驗證工具一開始就用「不確定就擋、由人放行」設計，不要先寫聰明規則再讓審閱一條一條挑。
- 回測要用最終版重跑並寫進 PR 描述，不要沿用改規則前的數字（這次改配對規則後 PASS 版的 shifted／changed 數字就變了兩次）。
- `gh pr edit` 在這個環境會被 GitHub Projects classic 的警告擋住，改用 `gh api -X PATCH repos/<o>/<r>/pulls/<N> -F body=@檔`。

## 隔離聲明

只動 `scripts/verify_registry_evidence.py`、`tests/test_verify_registry_evidence.py`、`README.md`、`docs/session-wrap-up-sop.md`；沒有接觸 /opt /etc /var/lib、systemd、交易所、Google 或實機帳本。審閱者只讀 GitHub 與 PR 留言，沒有部署。
