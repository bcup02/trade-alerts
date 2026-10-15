# 等部署的未做格子要名「等哪個提交」＋觀察區偵測 registry-awaits（phase-sync1） 審閱歸檔

- PR：bcup02/trade-alerts#193
- head：7de05f19da3f57e9d4e5d02a65bcf07ccd736da6（首審 8bc5d04c04cceaf869f9b0151ee170dd89fd9d3d）／ base：f5126ba845eed2ae16582437afb2a81d8e19701a ／ squash：376ab4a8eb6a44d14505db6300870a4632f752dd
- 審閱：ChatGPT，2 輪（第 1 輪 BLOCK，第 2 輪 PASS；審閱PR#193結論：PASS）
- CI run：38674669281（981 passed；首審 38673592094 為 978，baseline 961＋17＋3）
- 重點：registry_problems 規則——未做格的理由承諾部署（上正式機後改已做、還沒上正式機、未部署、未發版…）必須帶 awaits_commit（7～40 位小寫十六進位，只准在未做格；schema 同步）；觀察區偵測新檢查 registry-awaits（讀 origin/main 登記冊，問 A1 各策略部署複本 HEAD〔白名單固定目錄、只准 rev-parse HEAD〕，用 merge-base --is-ancestor 判斷等的提交是否已在 A1）；文件與收尾 SOP。真 A1 唯讀端到端演練：只點名 A1 已跑那個提交的格子。
- 首審 BLOCK（一點，真問題）：登記冊所在 repo 的 git fetch 失敗時，_refresh 忽略結果，可能讀到舊 origin/main（沒有待比對格）而回報「沒有東西要比對」，把資料過時掩蓋成正常。修正：_refresh 回傳 True／False／None；trade-alerts 的 fetch 失敗 → RemoteError（轉成 error 條目、連續 3 次通知）；策略 repo 的 fetch 失敗維持非致命（cat-file 與 merge-base 明確檢查）；observed 同時列出仍在等的格子。補 3 個測試，反向驗證通過。
- 審閱接受的取捨／留給後續的邊界：片語偵測可被換說法繞過（更強做法＝phase-sync4）；A1 部署複本 HEAD 是部署的代理；fetch 成功但 origin/main 未必對應遠端 main（remote.origin.fetch 設定被改）、沒有 origin 或覆寫 OBSERVATION_WATCH_REGISTRY_REF 時仍可能讀舊資料——開發機現況 refspec 為 +refs/heads/*:refs/remotes/origin/*，已確認；後續可加 ref 新鮮度檢查。
- 部署：合併後開發機已重裝 observation-watch（/opt/observation-watch 與 main 同檔），手動跑 registry-awaits：目前沒有帶 awaits_commit 的格子，回報「沒有東西要比對」；A1 與策略未動。
- 隔離聲明：審閱端未接觸實機；PASS 不授權部署。
