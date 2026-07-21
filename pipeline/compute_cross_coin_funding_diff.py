"""跨幣費率差（比較題殺手鐧）：對照 02改_資料網格.html 的
`cross-coin-funding-diff` spec（狀態：local，本地計算／零外部 API）。跟正式
`agent/collectors/` 還沒有對應模組，這裡先是 prototype，屬於「衍生品類」缺口
的一部分（跟 CME COT／訂單簿深度／多空帳戶比／期貨到期結構／費率擁擠度／
選擇權 IV／OI×價格四象限／CEX vs DEX 費率差同一批，都還沒併回正式 collector）。

不新增 API：複用 `fetch_funding_rate_percentile.py` 已經算好、寫在
raw_data/derivatives/{COIN}/funding_rate_percentile_snapshot.json 的
percentile_30d，兩幣百分位相減，純本地運算，零外部 API call。

跟 compute_relative_strength.py 同一套「比較題」慣例：A/B 由題目指定哪兩幣
比較，不是固定配對，五幣各自掛一顆 chip，所以算全部 5×4=20 個方向組合（A-B
跟 B-A 互為正負號，但證據句分別掛在 A、B 各自名下，題目可能問「BTC 比 SOL
擁擠嗎」也可能問「SOL 比 BTC 擁擠嗎」）。

用法：
    先跑過 python pipeline/fetch_funding_rate_percentile.py（五幣快照缺任何
    一份都會直接報錯，不會用舊資料硬湊）
    python pipeline/compute_cross_coin_funding_diff.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from itertools import permutations
from pathlib import Path

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
DERIVATIVES_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "derivatives"
OUTPUT_DIR = DERIVATIVES_DIR / "cross_coin_funding_diff"

# 擁擠度落差門檻（百分位點數）：超過這個差距才判「明顯較擁擠/較寬鬆」，避免
# 小差距被誤讀成訊號；跟 cex-dex-funding-diff 的 5% 年化門檻同樣是刻意取捨，
# 賽前如果覺得太鬆/太緊可以再跟 Ken 討論調整。
GAP_THRESHOLD_POINTS = 40.0


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_percentile(coin: str) -> dict:
    path = DERIVATIVES_DIR / coin / "funding_rate_percentile_snapshot.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} 不存在，先跑 python pipeline/fetch_funding_rate_percentile.py 補齊五幣快照"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def gap_label(diff: float, coin_a: str, coin_b: str) -> str:
    if diff >= GAP_THRESHOLD_POINTS:
        return f"{coin_a} 多頭倉位比 {coin_b} 擁擠得多、風險敞口更大"
    if diff <= -GAP_THRESHOLD_POINTS:
        return f"{coin_a} 多頭倉位比 {coin_b} 寬鬆得多、風險敞口較小"
    return f"{coin_a} 與 {coin_b} 擁擠度接近，無明顯落差"


def build_result(coin_a: str, coin_b: str, snap_a: dict, snap_b: dict) -> dict:
    pct_a = snap_a["percentile_30d"]
    pct_b = snap_b["percentile_30d"]
    diff = round(pct_a - pct_b, 2)
    label = gap_label(diff, coin_a, coin_b)
    return {
        "coin_a": coin_a,
        "coin_b": coin_b,
        "percentile_30d_a": pct_a,
        "percentile_30d_b": pct_b,
        "percentile_diff": diff,
        "gap_label": label,
        "sentence": (
            f"[{coin_a} 費率 {pct_a:.1f} 百分位 vs {coin_b} 費率 {pct_b:.1f} 百分位] "
            f"差 {diff:+.1f} 點 → {label}"
        ),
        "source_fetched_at": {coin_a: snap_a["fetched_at"], coin_b: snap_b["fetched_at"]},
        "computed_at": now_iso(),
    }


def write_output(coin_a: str, coin_b: str, result: dict) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{coin_a}_{coin_b}_diff.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    snapshots = {coin: load_percentile(coin) for coin in COINS}
    for coin_a, coin_b in permutations(COINS, 2):
        result = build_result(coin_a, coin_b, snapshots[coin_a], snapshots[coin_b])
        out_path = write_output(coin_a, coin_b, result)
        print(f"{result['sentence']} → 已寫入 {out_path}")


if __name__ == "__main__":
    main()
