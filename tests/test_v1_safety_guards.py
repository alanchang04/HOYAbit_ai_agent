from agent.integrity import assess_integrity
from agent.reasoning.consistency import enforce_reasoning_consistency
from agent.reasoning.pipeline import ReasoningResult
from agent.schemas import Evidence, SourceType


def _evidence(
    number: int,
    source_type: SourceType,
    *,
    coin: str = "BTC",
    content: str = "fixture",
    fetched_at: str = "2026-08-01T00:00:00Z",
) -> Evidence:
    return Evidence(
        id=f"ev-{number:03d}",
        coin=coin,
        source=f"{source_type.value} fixture",
        fetched_at=fetched_at,
        content_reference=content,
        related_claim="fixture",
        source_type=source_type,
    )


def test_consistency_guard_normalizes_halving_age_across_all_sections():
    evidences = [
        _evidence(
            1,
            SourceType.MACRO,
            content=(
                "類型=halving｜上次2024-04-20：第 4 次減半，區塊高度 840,000｜"
                "下次預估2028-04-17"
            ),
        )
    ]
    result = ReasoningResult(
        question_type="multi_source",
        facts=[{"summary": "處於第4次減半後約2年3個月位置", "evidence_ids": ["ev-001"]}],
        debate={
            "bear_argument": "距第4次減半已約15個月，週期位置不利",
            "rounds": [{"bear_argument": "減半後約15個月仍需留意"}],
        },
        conclusion={
            "market_judgment": "減半後約15個月進入後期",
            "limitations": [],
        },
    )

    corrections = enforce_reasoning_consistency(result, evidences)

    assert len(corrections) == 3
    assert result.facts[0]["summary"] == "處於第4次減半後約2年3個月位置"
    assert "距第4次減半約2年3個月" in result.debate["bear_argument"]
    assert "減半後約2年3個月" in result.debate["rounds"][0]["bear_argument"]
    assert "減半後約2年3個月" in result.conclusion["market_judgment"]
    assert "15個月" not in str(result)


def test_consistency_guard_leaves_text_untouched_without_event_anchor():
    result = ReasoningResult(
        question_type="multi_source",
        conclusion={"market_judgment": "減半後約15個月"},
    )
    corrections = enforce_reasoning_consistency(
        result,
        [_evidence(1, SourceType.PRICE)],
    )
    assert corrections == []
    assert result.conclusion["market_judgment"] == "減半後約15個月"


def _complete_btc_evidence() -> list[Evidence]:
    return [
        _evidence(1, SourceType.PRICE),
        _evidence(2, SourceType.ONCHAIN),
        _evidence(3, SourceType.NEWS),
        _evidence(4, SourceType.SOCIAL),
        _evidence(5, SourceType.DERIVATIVES),
        _evidence(6, SourceType.MACRO),
    ]


def test_integrity_is_intact_when_all_expected_types_exist():
    assessment = assess_integrity(_complete_btc_evidence(), ["BTC"])
    assert assessment.status == "INTACT"
    assert assessment.reasons == []


def test_integrity_is_partial_when_a_source_category_is_missing():
    evidences = [
        evidence
        for evidence in _complete_btc_evidence()
        if evidence.source_type != SourceType.ONCHAIN
    ]
    assessment = assess_integrity(evidences, ["BTC"])
    assert assessment.status == "PARTIAL"
    assert assessment.reasons == ["BTC 缺少 onchain 資料"]


def test_integrity_is_degraded_when_pipeline_layer_failed():
    evidences = [
        evidence
        for evidence in _complete_btc_evidence()
        if evidence.source_type != SourceType.ONCHAIN
    ]
    assessment = assess_integrity(evidences, ["BTC"], ["推理鏈失敗，已輸出降級報告"])
    assert assessment.status == "DEGRADED"
    assert assessment.reasons == ["推理鏈失敗，已輸出降級報告"]
