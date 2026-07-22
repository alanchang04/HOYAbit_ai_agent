"""Phase 2 去重（R12-1）：標題/內容字串級近重複偵測，先去重再進權重計算。

設計權威：Ken《07_流程圖迭代定案.md》——去重搬到 Phase 2，同步算出
raw_count／deduped_count／dedup_rate 隨證據傳遞；去重前筆數 < min_sample
的群組標記 small_sample，dedup_penalty 固定為 1（R12-3d 小樣本防呆）。

只處理敘事類（news/social）證據——價格/鏈上/總經是決定性資料，
不存在「轉載/聯播」的去重問題。純本地字串運算，零 LLM 成本。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.filters.trust_config import get_dedup_min_sample, load_reputation_config
from agent.logging_utils import ExecutionLogger
from agent.schemas import (
    Evidence,
    FilterDecision,
    FilterVerdict,
    LogPhase,
    LogStatus,
    PipelineLayer,
    SourceType,
)

DEDUP_SIMILARITY_THRESHOLD = 0.8
DEDUP_SOURCE_TYPES = (SourceType.NEWS, SourceType.SOCIAL)


def jaccard_similarity(text_a: str, text_b: str) -> float:
    """計算兩段文字的小寫 token 集合 Jaccard 相似度。"""
    tokens_a = set(text_a.lower().split())
    tokens_b = set(text_b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


@dataclass
class DedupGroupStats:
    """單一 (coin, source_type) 群組的去重統計。

    distinct_sources 即 Ken 定義的「覆蓋度」（去重後獨立來源數），
    與 L5 信心公式的「覆蓋率」（collector 成功執行比例）是不同的量。
    """

    coin: str
    source_type: str
    raw_count: int
    deduped_count: int
    dedup_rate: float
    distinct_sources: int
    small_sample: bool

    def as_dict(self) -> dict:
        return {
            "coin": self.coin,
            "source_type": self.source_type,
            "raw_count": self.raw_count,
            "deduped_count": self.deduped_count,
            "dedup_rate": self.dedup_rate,
            "distinct_sources": self.distinct_sources,
            "small_sample": self.small_sample,
        }


@dataclass
class DedupResult:
    """apply_dedup 的完整輸出，供 source_weights 計算覆蓋度與 dedup_penalty。"""

    stats: list[DedupGroupStats] = field(default_factory=list)
    duplicate_of: dict[str, str] = field(default_factory=dict)  # dup id -> canonical id
    decisions: list[FilterDecision] = field(default_factory=list)

    def stats_for(self, evidence: Evidence) -> DedupGroupStats | None:
        for s in self.stats:
            if s.coin == evidence.coin and s.source_type == evidence.source_type.value:
                return s
        return None


def apply_dedup(
    evidences: list[Evidence],
    logger: ExecutionLogger,
    min_sample: int | None = None,
) -> DedupResult:
    """對 news/social 證據做群組內近重複去重，回傳統計＋剔除決定。

    - 群組鍵：(coin, source_type)；群組內依原始順序，首見者為 canonical
    - 相似度：content_reference 的 Jaccard ≥ 0.8 判為轉載/聯播
    - 被剔除者：記 FilterDecision(check_code="DEDUP", verdict=removed)，
      並在證據上標 duplicate_of；不從 evidence.json 刪除（保留可回溯）
    - 群組統計（raw/deduped/dedup_rate）回寫到該群組每一筆證據上
    """
    if min_sample is None:
        min_sample = get_dedup_min_sample(load_reputation_config())

    result = DedupResult()

    groups: dict[tuple[str, str], list[Evidence]] = {}
    for ev in evidences:
        if ev.source_type in DEDUP_SOURCE_TYPES:
            groups.setdefault((ev.coin, ev.source_type.value), []).append(ev)

    for (coin, source_type), group in groups.items():
        canonicals: list[Evidence] = []
        for ev in group:
            matched: tuple[Evidence, float] | None = None
            for canon in canonicals:
                sim = jaccard_similarity(ev.content_reference, canon.content_reference)
                if sim >= DEDUP_SIMILARITY_THRESHOLD:
                    matched = (canon, sim)
                    break
            if matched is None:
                canonicals.append(ev)
                continue

            canon, sim = matched
            ev.duplicate_of = canon.id
            result.duplicate_of[ev.id] = canon.id
            result.decisions.append(
                FilterDecision(
                    evidence_id=ev.id,
                    check_code="DEDUP",
                    verdict=FilterVerdict.REMOVED,
                    reason=(
                        f"與 {canon.id} 內容相似度 {sim:.2f} ≥ "
                        f"{DEDUP_SIMILARITY_THRESHOLD}，判定為轉載/聯播，"
                        f"去重（保留 {canon.id}）"
                    ),
                )
            )

        raw_count = len(group)
        deduped_count = len(canonicals)
        dedup_rate = round(1 - deduped_count / raw_count, 4) if raw_count else 0.0
        stats = DedupGroupStats(
            coin=coin,
            source_type=source_type,
            raw_count=raw_count,
            deduped_count=deduped_count,
            dedup_rate=dedup_rate,
            distinct_sources=len({c.source for c in canonicals}),
            small_sample=raw_count < min_sample,
        )
        result.stats.append(stats)

        # R12-1：統計隨證據一併保存（進 evidence.json）
        for ev in group:
            ev.dedup_raw_count = raw_count
            ev.dedup_deduped_count = deduped_count
            ev.dedup_rate = dedup_rate

    for d in result.decisions:
        logger.log(
            phase=LogPhase.COLLECT,
            action="l2_dedup",
            detail=f"{d.evidence_id}: {d.reason}",
            status=LogStatus.OK,
            layer=PipelineLayer.CONTENT,
            metrics={
                "evidence_id": d.evidence_id,
                "check_code": d.check_code,
                "verdict": d.verdict.value,
            },
        )

    logger.log(
        phase=LogPhase.COLLECT,
        action="l2_dedup_summary",
        detail=(
            f"groups={len(result.stats)}, removed={len(result.decisions)}, "
            f"min_sample={min_sample}"
        ),
        status=LogStatus.OK,
        layer=PipelineLayer.CONTENT,
        metrics={
            "groups": [s.as_dict() for s in result.stats],
            "removed_total": len(result.decisions),
            "min_sample": min_sample,
        },
    )

    return result
