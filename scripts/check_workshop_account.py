"""Workshop Studio 帳號探測：貼上臨時憑證後，問帳號「你到底有什麼」。

競賽用的 AWS Workshop Studio 帳號與我們開發用的個人帳號有三處硬性差異，
每一處都會讓現有 `.env` 直接失效：

  1. **可用 region 不同**——本次事件只開 us-west-2 / us-east-1，
     我們開發時用的 ap-northeast-1 不在其中。
  2. **模型 ID 綁帳號也綁 region**——原設定是
     `arn:aws:bedrock:ap-northeast-1:<開發帳號>:inference-profile/jp.anthropic...`，
     帳號、region、`jp.` 跨區前綴三者全錯。
  3. **憑證是臨時的**——Workshop Studio 發的是 STS 短期憑證，
     除了 key/secret 還必須帶 `AWS_SESSION_TOKEN`，且會過期需重取。

與其憑記憶猜哪個模型 ID 可用，不如直接問帳號。這支腳本**只讀不寫**，
每一步獨立 try/except——某一步沒權限也會繼續跑完其餘檢查，
因為 Workshop 帳號常以 SCP 限制服務清單，看得到哪些被擋本身就是情報。

使用方式：
    # 先把 Workshop Studio「Get AWS CLI credentials」給的三個值寫進 .env
    python scripts/check_workshop_account.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from agent.config import get_settings

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 本次事件開放的 region（見 Workshop Studio 事件頁 Accessible Regions）
EVENT_REGIONS = ("us-west-2", "us-east-1")

# 競賽規定只能用 Bedrock／SageMaker 的基礎模型，這裡只找 Anthropic 家族。
WANTED_PROVIDER = "anthropic"


def _hr(title: str) -> None:
    print(f"\n{'=' * 66}\n{title}\n{'=' * 66}")


def check_identity() -> str | None:
    """確認憑證有效、印出帳號 id。回傳帳號 id 供後續組 ARN 用。"""
    _hr("1. 憑證是否有效")
    if not os.getenv("AWS_SESSION_TOKEN"):
        print("[警告] 沒有偵測到 AWS_SESSION_TOKEN。")
        print("      Workshop Studio 發的是臨時憑證，缺這個 token 一定會被拒絕。")
    try:
        ident = boto3.client("sts").get_caller_identity()
    except (ClientError, BotoCoreError) as exc:
        print(f"[FAIL] 取不到身分：{exc}")
        print("      → 憑證沒設好或已過期。回 Workshop Studio 重按 Get AWS CLI credentials。")
        return None
    print(f"[OK] 帳號 ID：{ident['Account']}")
    print(f"     身分    ：{ident['Arn']}")
    return ident["Account"]


def list_models(region: str) -> list[str]:
    """列出該 region 可用的 Anthropic 基礎模型。"""
    print(f"\n--- {region}：基礎模型 ---")
    try:
        models = boto3.client("bedrock", region_name=region).list_foundation_models(
            byProvider=WANTED_PROVIDER
        )["modelSummaries"]
    except (ClientError, BotoCoreError) as exc:
        print(f"  [跳過] 列不出來：{type(exc).__name__}")
        return []
    ids = [m["modelId"] for m in models]
    if not ids:
        print("  （沒有任何 Anthropic 模型）")
    for mid in ids:
        print(f"  · {mid}")
    return ids


def list_inference_profiles(region: str) -> list[str]:
    """列出跨區推論設定檔——**多數新模型只能透過它呼叫，不能用裸模型 id**。

    我們在開發帳號上就是踩這個坑：裸的 Claude 模型 id 一律被拒
    （provider 標記 legacy／帳號無使用紀錄），最後是靠推論設定檔才通的。
    """
    print(f"\n--- {region}：推論設定檔（優先用這個）---")
    try:
        profiles = boto3.client("bedrock", region_name=region).list_inference_profiles()[
            "inferenceProfileSummaries"
        ]
    except (ClientError, BotoCoreError) as exc:
        print(f"  [跳過] 列不出來：{type(exc).__name__}")
        return []
    ids = [
        p["inferenceProfileId"]
        for p in profiles
        if WANTED_PROVIDER in p["inferenceProfileId"].lower()
    ]
    if not ids:
        print("  （沒有 Anthropic 推論設定檔）")
    for pid in ids:
        print(f"  · {pid}")
    return ids


def try_converse(region: str, model_id: str) -> bool:
    """實際發一次最小呼叫——列得出來不等於叫得動（模型存取權要另外開通）。"""
    try:
        resp = boto3.client("bedrock-runtime", region_name=region).converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": "回覆 OK 兩個字即可"}]}],
            inferenceConfig={"maxTokens": 20, "temperature": 0},
        )
        text = resp["output"]["message"]["content"][0]["text"].strip()
        print(f"  [可用] {model_id} → {text!r}")
        return True
    except (ClientError, BotoCoreError) as exc:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)
        print(f"  [不可用] {model_id} → {code}")
        return False


def main() -> int:
    settings = get_settings()

    _hr("0. 目前 .env 設定（改之前先看一眼）")
    print(f"  AWS_REGION       = {settings.aws_region}")
    print(f"  BEDROCK_MODEL_ID = {settings.bedrock_model_id}")
    if settings.aws_region not in EVENT_REGIONS:
        print(f"  [必須改] 此 region 不在本次事件開放清單 {EVENT_REGIONS} 內。")
    if ":" in settings.bedrock_model_id and "arn:" in settings.bedrock_model_id:
        print("  [必須改] 目前是綁帳號的 ARN，換帳號必定失效。")

    if check_identity() is None:
        return 1

    _hr("2. 這個帳號有哪些模型可用")
    candidates: list[tuple[str, str]] = []
    for region in EVENT_REGIONS:
        profiles = list_inference_profiles(region)
        models = list_models(region)
        # 推論設定檔優先（開發帳號的經驗：裸模型 id 常被拒）
        candidates += [(region, pid) for pid in profiles]
        candidates += [(region, mid) for mid in models]

    if not candidates:
        print("\n[FAIL] 兩個 region 都列不到 Anthropic 模型。")
        print("      → 可能是 SCP 擋住 bedrock:List*，或帳號尚未開通模型存取。")
        print("      → 仍可直接跑第 3 步試呼叫，列不出來不代表叫不動。")

    _hr("3. 實際試呼叫（列得出來 ≠ 叫得動）")
    working: list[tuple[str, str]] = []
    # Sonnet 系列優先試，其次其他；每個 region 最多試 6 個免得跑太久
    def _rank(item: tuple[str, str]) -> tuple[int, str]:
        _, mid = item
        return (0 if "sonnet" in mid.lower() else 1, mid)

    for region in EVENT_REGIONS:
        in_region = sorted([c for c in candidates if c[0] == region], key=_rank)[:6]
        if in_region:
            print(f"\n--- {region} ---")
        for _, model_id in in_region:
            if try_converse(region, model_id):
                working.append((region, model_id))

    _hr("4. 建議寫進 .env 的設定")
    if working:
        region, model_id = working[0]
        print("  複製以下兩行覆蓋 .env 對應欄位：\n")
        print(f"    AWS_REGION={region}")
        print(f"    BEDROCK_MODEL_ID={model_id}")
        print(f"\n  （本次共 {len(working)} 個可用組合，上面挑的是最優先的一個）")
        for r, m in working[1:]:
            print(f"    備援：{r} / {m}")
        return 0

    print("  [FAIL] 沒有任何可用組合。請確認：")
    print("    a) Bedrock 主控台 → Model access 是否已開通 Anthropic 模型")
    print("    b) 憑證是否過期（Workshop Studio 的 token 有時效）")
    print("    c) 是否被 SCP 擋住")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
