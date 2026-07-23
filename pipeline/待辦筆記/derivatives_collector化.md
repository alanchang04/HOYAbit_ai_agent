# Derivatives 正式化成 collector 待辦

✅ 已解決（2026-07-22）：七項（費率擁擠度／OI×價格四象限／多空帳戶比背離／
期貨到期結構／CME COT／選擇權 IV/Skew／CEX-DEX 費率差）全併成正式
`agent/collectors/derivatives.py`，`pytest -q` 196 全過，BTC/BNB 真實 API
都測過。**兩項刻意不併入**：跨幣費率差（雙幣比較題專用，介面不合單幣種
`fetch(coin)`）、清算流（45 秒 WebSocket 監聽全市場，跟其他子來源模型不同）。
完整記錄見 `流程紀錄.md` 開頭那段。**尚未跟 alanchang 討論**，目前只在
`ken` 分支，`schemas.py`／`orchestrator.py`／`source_weights.py`／
`fixtures/dry_run_evidence.json` 這四個共用檔案有改動，PR 前要先跟他過一輪。

## 待 Ken 補的筆記

-
