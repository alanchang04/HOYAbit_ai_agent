# 版本 1 保存與回退方案

> 建立於 2026-08-01，v2（依 `11流程圖模板.md` 改版）動工前。
> 目的：v2 隨時可以放棄，五分鐘內回到可交付的 v1。

## v1 是什麼

| 項目 | 值 |
|---|---|
| Tag | **`v1.2-final`**（回退／團隊同步請用這個；`v1.0`／`v1.1`／`v1.2` 都缺後續回補） |
| Commit | `1ac176e` |
| 保護分支 | `release/v1`（與 tag 同點，供 v1 熱修） |
| 部署位置 | http://52.33.16.251/ （EC2 `i-0f7f925714b7e2b30`，us-west-2，需重新部署此 tag） |
| 驗收狀態 | 834 測試通過；命題三題型皆經真實 Bedrock 驗證（延續 v1.1 驗收基礎） |
| 相對 v1.1 的新增 | 裁判逐點判定＋Bedrock 真 15 分鐘硬限制、prompt injection 偵測與隔離、HTML 離線輸出＋完整性三態、雙幣種題型優先判 comparison、Step A grounding 稽核（防止幻覺數值/指標流入辯論鏈）、related_claims 附加結構、CLI 每次執行獨立 run id、統一 Evidence Validation Result＋真正的 Invalid Evidence quarantine、collector 成功呼叫補記 endpoint/params log |
| 相對 v1.2 的新增 | Codex 的 research context sidecar（`agent/research/`）——唯讀、不改 Evidence／ReasoningResult／confidence、不進 LLM prompt，reasoning 跑完後才寫一次，失敗自動隔離；並反過來讀 v1.2 的 validation_results 偵測 gate 是否洩漏 |

`v1.0`／`v1.1`／`v1.2`／`v1.2-final` 都是 **annotated tag**，內容不可變。就算 `main` 被 v2 寫爛、分支被刪，
`git checkout v1.2-final` 永遠拿得回這份程式碼與當時的 `raw_data/`（資料已納入版控）。

## 獨立 Live Demo（與共用機器分開，2026-08-02 新建）

`i-0f7f925714b7e2b30`（52.33.16.251）是共用機器，之後可能被切換部署別的版本／分支。
為了讓 v1.2-final 有一個**不會被之後任何操作影響**的展示網址，另外開了一台獨立機器：

| 項目 | 值 |
|---|---|
| 展示網址 | http://52.39.99.236/（**Elastic IP**，已釘住，重開機/停機都不會變；剛開機時的原始公網 IP 是 35.91.6.73，已棄用） |
| Instance ID | `i-009224c9a0802fa4d`（Name tag: `hoyabit-v1.2-final-demo`） |
| Elastic IP | `eipalloc-0e50f0b4e86ea0dbd`（Name tag: `hoyabit-v1.2-final-demo-eip`） |
| Region | us-west-2 |
| 部署內容 | 固定跑 `v1.2-final`（clone 時直接 `--branch v1.2-final`，不是共用機器那種可切換 ref 的部署方式） |
| 管理方式 | 同樣走 SSM（沒開 22 port／無 key pair），跟共用機器共用同一個 IAM instance profile（`hoyabit-agent-instance-profile`）與 security group（`sg-049e054aa0dfa3723`，僅開 80 port） |
| 已驗證 | SSM 確認 `git describe --tags` 回報 `v1.2-final`、`systemctl is-active hoyabit` = active、機器內與外部 curl 皆回 HTTP 200 |

這台機器**不會自動跟著 `release/v1` 更新**——它是釘死在 v1.2-final 這個 commit 的獨立快照，之後若要更新版本，需要手動重跑一次部署（目前沒有腳本化，需要重新走一次 launch，或視需要幫它補一支類似 `deploy_ec2.py` 但指向 `i-009224c9a0802fa4d` 的腳本）。

**`release/v1` 是保護分支，之後除非是同等級的唯讀／可隔離降級小修正，否則不應再有新東西直接推上來**——新的開發（尤其 v2 相關）一律走獨立分支，merge 前要先確認過，不要重演這次「兩個人各自直接推同一條保護分支」的情況。

## 三道退路（由輕到重）

### 1. 只回退部署（最常用，約 1 分鐘）

v2 開發期間評審或隊友要看 demo，但 `main` 上是半成品：

```bash
python scripts/deploy_ec2.py --ref v1.2-final  # 回到 v1
python scripts/deploy_ec2.py --status       # 確認機器現在跑哪一版
python scripts/deploy_ec2.py --ref v2-dev   # 再切回 v2 繼續開發
```

機器與程式碼互相獨立——**部署哪一版與 `main` 指向哪裡無關**，
所以 v2 可以邊做邊壞，不影響對外展示。

### 2. 回退程式碼（v2 方向錯了）

```bash
git checkout release/v1        # 直接在 v1 基礎上繼續
# 或把 main 拉回 v1：
git push origin v1.2-final:main --force-with-lease
```

用 `--force-with-lease` 而非 `--force`：若期間有人推了東西上去，
指令會拒絕執行而不是默默蓋掉別人的工作。

### 3. 機器整台重建（機器被弄壞了）

`scripts/deploy_ec2.py` 只更新程式碼，不重建機器。若機器本身壞了
（服務起不來、磁碟滿、被誤刪），用當初的部署腳本重開一台，
user-data 會自動 clone 指定版本並啟動。IAM 角色、安全群組、Elastic IP
都還在，重新綁定即可。

## v2 的工作方式

```
main  ────────●  v1.2-final ← 永遠保持可交付、可展示
              │
              └──● v2-dev ← 所有 v2 改動在這裡
```

**規則**：

1. **`main` 在 v2 驗收通過前不動。** 交付項目包含 GitHub 連結，
   評審點進去看到的必須是完整可運作的版本，不是半成品。
2. v2 一律在 `v2-dev` 分支進行。
3. v2 要合併進 `main` 前，至少要達到 v1 的驗收水準：
   - 全套測試通過
   - 命題三種題型各跑一次真實 Bedrock，皆能完整產出四份交付檔
   - 部署後網頁與四面板正常
4. **合併前先在 `main` 上打 `v1.2`、`v1.3`…** 標記 v1 的任何熱修，
   確保回退點永遠是最新的可用 v1，而不是三天前的。

## 需要注意的邊界

- **Workshop 帳號 8/2 之後會回收**，屆時部署與 Elastic IP 一併消失。
  程式碼與 tag 在 GitHub 上不受影響，但「部署回退」這條路會失效。
  若需要長期存活的展示網址，得改部署到自有帳號。
- `.env`（含 Workshop 臨時憑證）不在版控內，回退不會還原它。
  換機器或憑證過期時要重新填，格式見 `.env.example`。
- v2 若改動 `raw_data/` 的格式，回退 v1 時資料也會一併回到 v1 版本
  （資料已納入版控），不會出現「新資料配舊程式」的錯配。
