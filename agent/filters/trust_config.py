"""載入 static/source_reputation.json（信任評分設定，R12-3a）。

載入或驗證失敗時回傳 None，呼叫端（source_weights / dedup）SHALL 退回
舊制規則表，不得中斷流程（R12-5）。設定值全部資料驅動：dedup_penalty
分級曲線等待校準項目只需改 JSON，不需改程式。
"""

from __future__ import annotations

import json
from pathlib import Path

STATIC_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "static" / "source_reputation.json"
)

# R12-3d 小樣本防呆的保底值（設定檔缺漏時使用）
DEFAULT_MIN_SAMPLE = 5


def load_reputation_config(path: Path | str | None = None) -> dict | None:
    """讀取並粗驗證信譽表設定，任何失敗都回 None（呼叫端負責 fallback）。"""
    try:
        config_path = Path(path) if path else STATIC_CONFIG_PATH
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            return None
        # 必要區塊缺一即視為壞檔，整體退回舊制（避免半套公式產生難解數字）
        if not isinstance(config.get("levels"), dict) or not config["levels"]:
            return None
        if not isinstance(config.get("level_order"), list) or not config["level_order"]:
            return None
        if not isinstance(config.get("rules"), list) or not config["rules"]:
            return None
        if any(lv not in config["levels"] for lv in config["level_order"]):
            return None
        return config
    except Exception:
        return None


def get_dedup_min_sample(config: dict | None) -> int:
    """取出去重小樣本門檻（R12-3d），設定缺漏時用保底值。"""
    if not config:
        return DEFAULT_MIN_SAMPLE
    try:
        return int(config.get("dedup_penalty", {}).get("min_sample", DEFAULT_MIN_SAMPLE))
    except (TypeError, ValueError):
        return DEFAULT_MIN_SAMPLE
