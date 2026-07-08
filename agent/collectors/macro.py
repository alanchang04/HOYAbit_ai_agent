"""總體經濟 collector：Fear & Greed Index（免 key）＋ 美元指數 DXY（stooq 免 key CSV）。

若使用者提供 FRED 免費 key，可額外疊加美債殖利率等指標（補充來源）。
"""

from __future__ import annotations

import httpx

from agent.collectors.base import BaseCollector
from agent.schemas import EvidenceDraft, LogStatus, now_iso

HTTP_TIMEOUT = 20.0


class MacroCollector(BaseCollector):
    name = "macro_collector"
    source_type = "macro"

    async def fetch(self, coin: str, **kwargs) -> list[EvidenceDraft]:
        evidences: list[EvidenceDraft] = []

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            try:
                resp = await client.get("https://api.alternative.me/fng/", params={"limit": 1})
                resp.raise_for_status()
                item = resp.json()["data"][0]
                evidences.append(
                    EvidenceDraft(
                        coin=coin,
                        source="Fear & Greed Index (alternative.me)",
                        source_url="https://api.alternative.me/fng/",
                        fetched_at=now_iso(),
                        content_reference=f"value={item.get('value')}, classification={item.get('value_classification')}, timestamp={item.get('timestamp')}",
                        related_claim="整體加密市場情緒指標",
                        source_type="macro",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self.log_subsource("fear_greed", coin, LogStatus.ERROR, f"error={exc}")

            try:
                # stooq 已加上瀏覽器 JS 驗證機制，無法穩定免 key 存取；改用 Frankfurter（歐洲央行公開匯率
                # API，免 key、穩定）以 USD/EUR 匯率變化作為美元強弱的簡易總經代理指標。
                resp = await client.get(
                    "https://api.frankfurter.app/latest", params={"from": "USD", "to": "EUR,JPY,GBP"}
                )
                resp.raise_for_status()
                data = resp.json()
                rates = data.get("rates", {})
                evidences.append(
                    EvidenceDraft(
                        coin=coin,
                        source="Frankfurter 美元匯率（歐洲央行公開資料，美元強弱代理指標）",
                        source_url="https://api.frankfurter.app/latest?from=USD",
                        fetched_at=now_iso(),
                        content_reference=f"date={data.get('date')}, USD/EUR={rates.get('EUR')}, USD/JPY={rates.get('JPY')}, USD/GBP={rates.get('GBP')}",
                        related_claim="美元相對強弱走勢（總經背景，加密市場常呈負相關）",
                        source_type="macro",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self.log_subsource("frankfurter_fx", coin, LogStatus.ERROR, f"error={exc}")

            if self.settings and getattr(self.settings, "fred_api_key", None):
                try:
                    resp = await client.get(
                        "https://api.stlouisfed.org/fred/series/observations",
                        params={
                            "series_id": "DGS10",
                            "api_key": self.settings.fred_api_key,
                            "file_type": "json",
                            "sort_order": "desc",
                            "limit": 1,
                        },
                    )
                    resp.raise_for_status()
                    obs = resp.json()["observations"][0]
                    evidences.append(
                        EvidenceDraft(
                            coin=coin,
                            source="FRED DGS10（10年期美債殖利率，補充來源）",
                            source_url="https://fred.stlouisfed.org/series/DGS10",
                            fetched_at=now_iso(),
                            content_reference=f"date={obs.get('date')}, value={obs.get('value')}",
                            related_claim="美債殖利率走勢（總經背景）",
                            source_type="macro",
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    self.log_subsource("fred", coin, LogStatus.SKIPPED, f"error={exc}")

        return evidences
