# PR #372 審閱歸檔：接收端支援用分頁固定編號登記（sheet_id），分頁改名不必發版（v0.30.39）

- PR：bcup02/trade-alerts #372；squash `4ec7440`（tag `v0.30.39`）；審閱 AI：ChatGPT；結論：第 1 輪 BLOCK、第 2 輪 PASS（head `e355d41` → `56ef4bb`，CI run 44089291093 → 44090987386，1666 passed）
- 範圍：`apps_script/google_ledger_receiver.gs`（來源登記可記 `sheet_id`、用編號找分頁；唯讀 `list_by_sheet` 可用 `project_id`；`listSheetIdsForRegistration`）、`tests/apps_script_sheet_id_node_test.js`、版本 0.30.39。

## 緣起
使用者要把 Google 表的舊分頁改名並拆出「競賽策略・流星版」新分頁；接收端登記與各策略程式都用分頁名稱找分頁，改名會讓寫表失敗。這是三步中的第 1 步（接收端），第 2 步開發機拆分頁、第 3 步正式機另做。

## 審閱歷程
| 輪 | head | 結論 | 內容 |
|---|---|---|---|
| 1 | `e355d41` | BLOCK | `registeredSourceForProject` 比較的是登記的寫法（`id:111` 對 `name:…`），同一個分頁以名稱與編號各登記一筆被誤判 `project_ambiguous`；測試只有「同編號」「不同編號」兩種組合，沒攔住 |
| 2 | `56ef4bb` | PASS | 改為先解析成實際分頁、比 `getSheetId()`；解析不到的登記自成目標（與解析得到的並存仍歧義）；新增四種混合登記測試（以舊程式反向驗證會失敗）；corrective diff 只有 `.gs` 與測試 |

## 已知缺口與後續
1. 接收端腳本尚未部署（先 DEV，正式機等舊趨勢策略下線與競賽策略・流星版上線再一起）；審閱 PASS 不代表部署通過。
2. 程式沒有禁止管理員把來源登記到 `Google_Provenance_Audit` 的編號；屬登記設定的防護議題，非繞過路徑，後續可考慮加黑名單。
3. 兩個不同名稱、都解析不到的登記判歧義的路徑沒有獨立測試（審閱者以程式路徑核對）。
4. 其他三支策略與舊趨勢策略仍用名稱登記，要在一致性登記冊登記「未做」。

## 教訓
1. 比較「兩筆設定是否指向同一個東西」要比解析後的實體身分，不是比設定的寫法；測試要有「同一實體、不同表示法」的組合。
