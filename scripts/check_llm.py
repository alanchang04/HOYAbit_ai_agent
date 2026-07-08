"""LLM backend 連線驗證腳本：依 .env 的 LLM_BACKEND 設定，發一個最小 prompt 確認可用。

使用方式：
    python scripts/check_llm.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.config import get_settings
from agent.reasoning.llm_client import build_llm_client

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def main() -> int:
    settings = get_settings()
    print(f"LLM_BACKEND={settings.llm_backend}")
    if settings.llm_backend.lower() != "bedrock":
        print("[警告] 目前不是 bedrock，這是開發階段暫代用後端，正式比賽前記得切回 bedrock。")

    try:
        client = build_llm_client(settings)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 無法建立 LLM client: {exc}", file=sys.stderr)
        return 1

    try:
        reply = client.converse(
            system_prompt="你是連線測試用的助理，只需簡短回應。",
            user_prompt="請回覆「連線成功」四個字，不要有其他內容。",
            max_tokens=50,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 呼叫失敗: {exc}", file=sys.stderr)
        return 1

    print(f"[OK] 模型回應：{reply.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
