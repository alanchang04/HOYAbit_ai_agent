"""把指定的 git ref 部署到 EC2（也就是回退／升版的唯一入口）。

用法：
    python scripts/deploy_ec2.py                 # 部署 origin/main（預設）
    python scripts/deploy_ec2.py --ref v1.0      # 回退到 v1.0
    python scripts/deploy_ec2.py --ref v2-dev    # 部署 v2 開發分支
    python scripts/deploy_ec2.py --status        # 只看機器現在跑哪個版本

**為什麼要有這支**：v2 改版期間隨時可能需要退回 v1 展示。把「部署」與「回退」
做成同一支帶參數的腳本，回退就不是一串要現想的指令，而是 `--ref v1.0`。
比賽現場沒有時間查指令。

走 SSM Run Command 而非 SSH：機器刻意沒開 22 port、也沒建 key pair，
維護通道走 IAM 授權的 SSM 比開 SSH 安全。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from agent.config import get_settings  # noqa: F401 - 觸發 .env 載入

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

REGION = "us-west-2"
INSTANCE_ID = "i-0f7f925714b7e2b30"
APP_DIR = "/opt/app"
SERVICE = "hoyabit"
PUBLIC_URL = "http://52.33.16.251/"


def _run(ssm, commands: list[str], timeout: int = 900) -> tuple[str, str, str]:
    """在機器上執行指令，回傳 (狀態, stdout, stderr)。"""
    cid = ssm.send_command(
        InstanceIds=[INSTANCE_ID],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": commands},
        TimeoutSeconds=min(timeout, 2172000),
    )["Command"]["CommandId"]

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(4)
        try:
            inv = ssm.get_command_invocation(CommandId=cid, InstanceId=INSTANCE_ID)
        except ClientError:
            continue  # 指令尚未派送到機器
        if inv["Status"] in ("Success", "Failed", "Cancelled", "TimedOut"):
            return (
                inv["Status"],
                inv.get("StandardOutputContent", "").strip(),
                inv.get("StandardErrorContent", "").strip(),
            )
    return "TimedOut", "", "等待逾時"


def show_status(ssm) -> int:
    status, out, err = _run(
        ssm,
        [f"cd {APP_DIR} && git log --oneline -1 && git describe --tags --always && systemctl is-active {SERVICE}"],
        timeout=120,
    )
    print(f"狀態: {status}\n{out}")
    if err:
        print(f"stderr: {err[:400]}")
    return 0 if status == "Success" else 1


def deploy(ssm, ref: str) -> int:
    print(f"▶ 部署 {ref} 到 {INSTANCE_ID}")

    # fetch 要同時抓分支與 tag，`--depth 1` 對 tag 也有效。
    # `git reset --hard` 之後跑 pip install：依賴可能隨版本變動，
    # 不重裝的話回退到舊版可能因為新版殘留的套件行為不一致。
    commands = [
        "set -e",
        f"cd {APP_DIR}",
        "git fetch --tags --force origin",
        f"git reset --hard {ref} 2>/dev/null || git reset --hard origin/{ref}",
        ".venv/bin/pip install -q -r requirements.txt",
        f"systemctl restart {SERVICE}",
        "sleep 5",
        f"systemctl is-active {SERVICE}",
        "git log --oneline -1",
    ]
    status, out, err = _run(ssm, ["\n".join(commands)])

    print(f"\n狀態: {status}")
    if out:
        print(f"--- 機器回報 ---\n{out}")
    if err and status != "Success":
        print(f"--- stderr ---\n{err[:1200]}")

    if status != "Success":
        print("\n[FAIL] 部署失敗，機器可能仍跑舊版。用 --status 確認實際版本。")
        return 1

    print(f"\n[OK] 已部署 {ref} → {PUBLIC_URL}")
    print("     建議接著開網頁確認頁面正常，再跑一次分析驗證。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="部署／回退 EC2 上的 webapp")
    parser.add_argument("--ref", default="origin/main", help="git ref（分支、tag 或 commit），預設 origin/main")
    parser.add_argument("--status", action="store_true", help="只顯示機器目前版本，不做任何變更")
    args = parser.parse_args()

    try:
        ssm = boto3.client("ssm", region_name=REGION)
        info = ssm.describe_instance_information(
            Filters=[{"Key": "InstanceIds", "Values": [INSTANCE_ID]}]
        )["InstanceInformationList"]
    except (ClientError, BotoCoreError) as exc:
        print(f"[FAIL] 連不上 AWS：{exc}\n     檢查 .env 的 Workshop 臨時憑證是否過期。", file=sys.stderr)
        return 1

    if not info:
        print(f"[FAIL] SSM 找不到 {INSTANCE_ID}（機器關了、或 SSM agent 未上線）", file=sys.stderr)
        return 1

    return show_status(ssm) if args.status else deploy(ssm, args.ref)


if __name__ == "__main__":
    raise SystemExit(main())
