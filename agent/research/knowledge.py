"""審核式 Knowledge Lite catalog。

Knowledge 只解釋 feature 的統計／市場語意，不替推理層產生方向結論。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent.research.models import KnowledgeCard, StructuredFeature


CATALOG_PATH = Path(__file__).resolve().parents[2] / "static" / "knowledge_lite.json"
_FORBIDDEN_DIRECTION_WORDS = ("bullish", "bearish", "看多", "看空")


def _contains_directional_conclusion(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False).lower()
    return any(word in text for word in _FORBIDDEN_DIRECTION_WORDS)


@lru_cache(maxsize=1)
def load_knowledge_catalog() -> dict[str, dict]:
    try:
        raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        name: card
        for name, card in raw.items()
        if isinstance(name, str)
        and isinstance(card, dict)
        and not _contains_directional_conclusion(card)
    }


def knowledge_for_features(features: list[StructuredFeature]) -> list[KnowledgeCard]:
    catalog = load_knowledge_catalog()
    cards: list[KnowledgeCard] = []
    for name in sorted({feature.name for feature in features}):
        payload = catalog.get(name)
        if payload is None:
            continue
        try:
            cards.append(KnowledgeCard(feature_name=name, **payload))
        except (TypeError, ValueError):
            # catalog 單一卡片損壞不應讓整份 sidecar 失敗。
            continue
    return cards

