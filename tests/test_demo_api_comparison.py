"""比較題：多幣種卡片餵進**同一條**推理鏈時，證據的幣種歸屬不能糊掉。

背景：demo 的 Stage 7-9 原本是單幣端點，比較題（「SOL 與 BTC 過去一年走勢比較」）
被前端拆成各幣一條獨立推理鏈——每條鏈只看得到自己的幣，結果誰都沒有做比較，
SOL 那條還會自己在 limitations 寫「缺乏 BTC 相關數據，無法完成比較走勢分析」。

修法是把兩個幣的卡片一次餵進同一條鏈（既有推理鏈本來就有 comparison 模式）。
這裡鎖住兩件容易在那個改動裡搞砸、而且壞掉時畫面上看不出來的事：

1. 每筆 Evidence 要帶**自己**的 coin——推理鏈的 `coins_with_evidence` 是從
   `Evidence.coin` 推的，全部蓋成同一個幣會讓它以為只有一個幣種有證據，
   比較框架整個失效（辯論會退回單幣的多空對打）。
2. 關係圖不可以跨幣連邊——`_build_evidence_graph` 內部用 `{card["factor"]: card}`
   當索引，兩個幣的卡片混在一起時同名 factor 會互相覆蓋。
"""

import pytest
from fastapi.testclient import TestClient

from webapp import stage1_demo_api
from webapp.stage1_demo_api import _cards_to_evidences, app


def _card(factor: str, coin: str, *, confirms: str | None = None) -> dict:
    return {
        "factor": factor,
        "evidence_id": f"{factor.upper()}_{coin}",
        "category": "derivatives",
        "fact": {"current_value": 1},
        "ranking_value": 0.3,
        "related_evidence": {"confirms": confirms} if confirms else {},
        "traceability": {"source": "test"},
    }


@pytest.fixture
def two_coin_cards() -> dict[str, list[dict]]:
    # funding_rate 的 confirms 指向 price：兩個幣都有這組，關係應該各自成對
    return {
        "SOL": [_card("funding_rate", "SOL", confirms="price"), _card("price", "SOL")],
        "BTC": [_card("funding_rate", "BTC", confirms="price"), _card("price", "BTC")],
    }


def test_each_evidence_keeps_its_own_coin(two_coin_cards):
    evidences, _ = _cards_to_evidences(two_coin_cards)

    by_id = {e.id: e for e in evidences}
    id_of = {e.content_reference: e for e in evidences}  # 只是為了錯誤訊息好讀
    assert len(evidences) == 4, id_of.keys()
    assert {e.coin for e in evidences} == {"SOL", "BTC"}
    # 每個幣各兩筆，不是四筆都掛在主幣底下
    assert sum(1 for e in evidences if e.coin == "SOL") == 2
    assert sum(1 for e in evidences if e.coin == "BTC") == 2
    assert all(by_id[e.id].coin for e in evidences)


def test_relations_never_cross_coins(two_coin_cards):
    evidences, id_map = _cards_to_evidences(two_coin_cards)

    coin_of_ev = {id_map[f"{f.upper()}_{c}"]: c
                  for c, cards in two_coin_cards.items()
                  for f in (card["factor"] for card in cards)}

    for e in evidences:
        for related_ids in (e.related_evidence or {}).values():
            for rid in related_ids:
                assert coin_of_ev[rid] == e.coin, (
                    f"{e.id}（{e.coin}）連到了 {rid}（{coin_of_ev[rid]}）——關係只存在同一個幣的證據之間"
                )


def test_every_card_gets_a_unique_ev_id(two_coin_cards):
    evidences, id_map = _cards_to_evidences(two_coin_cards)

    assert len(id_map) == 4
    assert len(set(id_map.values())) == 4
    assert {e.id for e in evidences} == set(id_map.values())


def test_single_coin_input_still_works():
    """單幣查詢走同一支函式，行為要跟改版前一致。"""
    evidences, id_map = _cards_to_evidences({"BTC": [_card("funding_rate", "BTC", confirms="price"), _card("price", "BTC")]})

    assert {e.coin for e in evidences} == {"BTC"}
    funding = next(e for e in evidences if e.related_claim == "funding_rate")
    assert funding.related_evidence["confirms"] == [id_map["PRICE_BTC"]]


# ---------------------------------------------------------------------------
# /api/stage789 的接線：推理鏈本身不在這裡測（846+ 測試已經涵蓋），這裡只驗
# 「demo 端點有沒有把比較題該傳的東西傳對」——coin2 有沒有傳、多幣證據有沒有
# 都進去。這兩件事錯了，畫面上看起來一切正常，只是辯論悄悄退回單幣框架。
# ---------------------------------------------------------------------------

class _FakeResult:
    question_type = "comparison"
    facts: list = []
    cross_validation: dict = {}
    inference: list = []
    debate: dict = {"round_count": 1}
    conclusion: dict = {"market_judgment": "比較結論"}
    confidence_score = 55
    confidence_breakdown: dict = {"base": 55}
    primary_horizon = "medium"
    primary_horizon_basis = "test"


@pytest.fixture
def spy_reasoning(monkeypatch):
    """攔下 run_reasoning，記錄實際收到的參數（不打任何 LLM）。"""
    seen: dict = {}

    def _fake(coin, question, evidences, dry_run=True, llm_client=None,
              log_step=None, coin2=None, logger=None, deadline=None,
              applicable_categories=None):
        seen.update(coin=coin, question=question, evidences=evidences, coin2=coin2)
        return _FakeResult()

    monkeypatch.setattr(stage1_demo_api, "run_reasoning", _fake)
    monkeypatch.setattr(stage1_demo_api, "build_llm_client", lambda settings: object())
    return seen


def test_comparison_request_passes_coin2_and_all_coins(spy_reasoning, two_coin_cards):
    client = TestClient(app)
    res = client.post("/api/stage789", json={
        "query": "SOL 與 BTC 過去一年走勢比較",
        "coin": "SOL",
        "cards_by_coin": two_coin_cards,
    })

    assert res.status_code == 200, res.text
    # coin2 沒傳＝辯論框架退回單幣多空對打，比較題就白做了
    assert spy_reasoning["coin2"] == "BTC"
    assert {e.coin for e in spy_reasoning["evidences"]} == {"SOL", "BTC"}
    assert len(spy_reasoning["evidences"]) == 4

    body = res.json()
    assert body["coin"] == "SOL" and body["coin2"] == "BTC"
    assert sorted(body["coins"]) == ["BTC", "SOL"]
    # 沒有跨幣相對指標是結構性缺口，必須回報給前端顯示，不能默默比較
    assert body["comparison_note"]


def test_single_coin_request_keeps_old_shape(spy_reasoning):
    client = TestClient(app)
    res = client.post("/api/stage789", json={
        "query": "BTC 未來兩週走勢",
        "coin": "BTC",
        "evidence_cards": [_card("funding_rate", "BTC")],
    })

    assert res.status_code == 200, res.text
    assert spy_reasoning["coin2"] is None
    assert res.json()["comparison_note"] is None


def test_main_coin_must_be_in_cards_by_coin(spy_reasoning, two_coin_cards):
    """主幣不在證據裡＝推理鏈會拿到一個沒有任何證據的主角，擋在門口比較好查。"""
    client = TestClient(app)
    res = client.post("/api/stage789", json={
        "query": "SOL 與 BTC 比較", "coin": "ETH", "cards_by_coin": two_coin_cards,
    })

    assert res.status_code == 400
    assert "ETH" in res.json()["detail"]
