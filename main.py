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

from agent.orchestrator import run_pipeline

SUPPORTED_COINS = {"BTC", "ETH", "SOL", "BNB", "XRP"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HOYA BIT 加密市場分析 AI Agent")
    parser.add_argument("--coin", required=True, help="幣種代號，如 BTC / ETH / SOL / BNB / XRP")
    parser.add_argument("--question", required=True, help="題目全文")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="使用 cached fixtures 跑完整流程，不打真實 API 或 Bedrock（賽前排練用）",
    )
    parser.add_argument("--output-dir", default=None, help="輸出目錄，預設 output/")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    coin = args.coin.upper()
    if coin not in SUPPORTED_COINS:
        print(f"[ERROR] 不支援的幣種: {coin}（支援：{', '.join(sorted(SUPPORTED_COINS))}）", file=sys.stderr)
        return 1

    if not args.dry_run:
        print(
            "[ERROR] 真實資料蒐集（Stage 2）已完成，但 Bedrock 四步推理鏈（Stage 3）尚未實作，"
            "目前仍僅支援 --dry-run。若想單獨驗證真實 collector，請用 scripts/test_collectors.py。",
            file=sys.stderr,
        )
        return 1

    result = run_pipeline(coin=coin, question=args.question, dry_run=args.dry_run, output_dir=args.output_dir)

    print(f"執行完成，耗時 {result.elapsed_seconds:.2f} 秒（degraded_mode={result.degraded_mode}）")
    print(f"證據筆數：{len(result.evidences)}")
    print("已產出 report.md / evidence.json / execution_log.jsonl 於輸出目錄。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
