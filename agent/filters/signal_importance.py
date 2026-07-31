"""載入 static/signal_importance.json（R8-3 靜態重要性係數，Ken 提案 Layer B 的簡化版）。

比照 `trust_config.py` 的模式：載入或驗證失敗一律回退預設值，不中斷流程
（R6-1）。介面刻意設計成「日後換成回測值只換 JSON、不改程式」——
`by_question_type` 是覆寫層，只在該題型下特定 source_type 的重要性與全域
預設不同時才需要列出。
"""

from __future__ import annotations

import json
from pathlib import Path

STATIC_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "static" / "signal_importance.json"
)

# 設定檔缺漏或載入失敗時的保底值：六類等權，不做任何調整（等同 R8-3 之前的行為）。
DEFAULT_IMPORTANCE = 1.0


def load_signal_importance_config(path: Path | str | None = None) -> dict | None:
    """讀取並粗驗證重要性係數設定，任何失敗都回 None（呼叫端負責 fallback）。"""
    try:
        config_path = Path(path) if path else STATIC_CONFIG_PATH
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            return None
        by_source_type = config.get("by_source_type")
        if not isinstance(by_source_type, dict) or not by_source_type:
            return None
        if not isinstance(config.get("by_question_type", {}), dict):
            return None
        return config
    except Exception:
        return None


def get_base_importance(
    source_type: str, question_type: str | None, config: dict | None
) -> float:
    """取出某 source_type 在某題型下的重要性係數。

    覆寫優先序：`by_question_type[question_type][source_type]` →
    `by_source_type[source_type]` → `DEFAULT_IMPORTANCE`（設定缺漏或壞檔時）。
    """
    if not config:
        return DEFAULT_IMPORTANCE
    try:
        if question_type:
            override = config.get("by_question_type", {}).get(question_type, {})
            if source_type in override:
                return float(override[source_type])
        by_source_type = config.get("by_source_type", {})
        if source_type in by_source_type:
            return float(by_source_type[source_type])
        return DEFAULT_IMPORTANCE
    except (TypeError, ValueError):
        return DEFAULT_IMPORTANCE
