"""加密市場分析 AI Agent CLI 進入點。

使用範例：
    python main.py --coin BTC --question "分析 BTC 過去兩週的市場表現..." --dry-run
"""

from __future__ import annotations

import argparse
import sys

if sys.platform == "win32":
    # Windows 終端機預設非 UTF-8 codepage，避免中文輸出亂碼
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from agent.collectors.coin_map import SUPPORTED_COINS
from agent.config import get_settings
from agent.orchestrator import run_pipeline


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HOYA BIT 加密市場分析 AI Agent")
    parser.add_argument("--coin", required=True, help="幣種代號，如 BTC / ETH / SOL / BNB / XRP")
    parser.add_argument("--question", required=True, help="題目全文")
    parser.add_argument(
        "--coin2",
        default=None,
        help="比較分析題型可選：第二個比較幣種代號。未提供時會嘗試從題目文字自動偵測",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="使用 cached fixtures 跑完整流程，不打真實 API 或 Bedrock（賽前排練用）",
    )
    parser.add_argument("--output-dir", default=None, help="輸出目錄，預設 output/")
    parser.add_argument(
        "--with-baseline",
        action="store_true",
        help="啟用未過濾對照組分析（同一 LLM 對全量證據做一次呼叫，作為信任提煉對比基準）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    coin = args.coin.upper()
    if coin not in SUPPORTED_COINS:
        print(f"[ERROR] 不支援的幣種: {coin}（支援：{', '.join(sorted(SUPPORTED_COINS))}）", file=sys.stderr)
        return 1

    coin2 = args.coin2.upper() if args.coin2 else None
    if coin2 and coin2 not in SUPPORTED_COINS:
        print(f"[ERROR] 不支援的 --coin2: {coin2}（支援：{', '.join(sorted(SUPPORTED_COINS))}）", file=sys.stderr)
        return 1

    if not args.dry_run:
        settings = get_settings()
        if settings.llm_backend.lower() != "bedrock":
            print(
                "=" * 70 + "\n"
                f"[警告] 目前 LLM_BACKEND={settings.llm_backend}，並非競賽規定的 Bedrock。\n"
                "此後端僅供開發階段暫代使用，正式執行/繳交前必須在 .env 把\n"
                "LLM_BACKEND 改回 bedrock，否則會違反「LLM 推理僅能使用 Bedrock」的硬性規定。\n"
                + "=" * 70,
                file=sys.stderr,
            )

    result = run_pipeline(
        coin=coin, question=args.question, dry_run=args.dry_run, output_dir=args.output_dir, coin2=coin2,
        with_baseline=args.with_baseline,
    )

    print(f"執行完成，耗時 {result.elapsed_seconds:.2f} 秒（degraded_mode={result.degraded_mode}）")
    print(f"證據筆數：{len(result.evidences)}")
    print("已產出 report.md / evidence.json / execution_log.jsonl 於輸出目錄。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
