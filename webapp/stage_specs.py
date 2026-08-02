"""Stage 2／Stage 5 規格檔讀取層——讓 demo 真的「去 Stage 2/3/4/5 資料夾抓」。

## 為什麼有這支檔

這支模組出現之前，`webapp/stage1_demo_api.py` 四層的資料來源並不一致：

| 層 | 規格檔 | 程式有沒有讀 |
|----|--------|------------|
| Stage 2 | `Stage 2 — Feature Extraction/{factor}.yaml` | ❌ 端點／參數／欄位清單全寫死在程式裡，yaml 只在註解裡被提到 |
| Stage 3 | `Stage 3 — Knowledge Layer/{factor}.md` | ✅ `_load_knowledge_md()` |
| Stage 4 | `Stage 4 — Dynamic Evidence Weight Engine/{factor}.md` | ✅ `_load_weight_md()` |
| Stage 5 | `Stage 5 — Evidence Card ＋ Prioritization/{factor}.md` | ❌ 卡片欄位寫死在 `_fact_summary()` |

Stage 3/4 已經是「.md 是單一事實來源，程式只負責讀」，Stage 2/5 還不是——改 yaml 不會改行為，
等於同一件事有兩份真相。這支模組補的就是 Stage 2/5 那兩格，讓四層走同一個模式。

## 規格檔驅動什麼、不驅動什麼（這條界線要講清楚，不然會被誤會）

**驅動**：端點、查詢參數、有哪些欄位、哪些欄位是結構性不存在（yaml 寫 `null`）、
卡片有哪些格子、哪一格是「對應到 Knowledge 的別的欄位」（`→ reaction_window`）。

**不驅動**：欄位的值。yaml 裡的 `percentile_rank(current_value, series)` 是**規格文字，
不是被執行的程式碼**——這裡沒有 eval，是照欄位名對到本檔實作的同名算法。所以規格檔改了
公式的文字敘述，行為不會跟著變；改的是「有沒有這個欄位」才會變。這是刻意的取捨：
真的去 eval 一份 .md 裡的字串，等於讓文件變成可執行程式碼，出錯時更難查。

## 已知的 YAML 限制（不是 bug，是 YAML 本身）

`persistence:`（留空）跟 `persistence: null`（明寫 null）解析出來都是 `None`，
分不出「這格由程式從 Knowledge 填」跟「這格結構性就是空的」。目前兩者都走「從 Knowledge 填」，
因為結構性空的那幾格（liquidation 的 persistence）在 Stage 3 本來就寫「不適用」，
填出來的結果一樣誠實。Stage 2 的 yaml 沒有這個問題——那邊有值的欄位都是公式字串，
明寫 `null` 的才是 None，兩者分得開。

## 已接進 stage1_demo_api.py（2026-08-02）

四個 Stage 2 端點與 Stage 5 組裝都已改用這支模組，跟著刪掉的寫死常數：
`ACTIVE_ADDRESS_ENDPOINT`／`ACTIVE_ADDRESS_SUPPORTED_COINS`（改讀 Stage 3 knowledge 的
`supported_assets`）／`CPI_ENDPOINT`（改讀 cpi.yaml 新增的 `value_source`）／
`LIQUIDATION_WS_URL`／`_fact_summary()`（卡片欄位的 if 鏈，改讀卡片 .md）。

呼叫長相：

    spec = load_feature_spec("funding_rate")
    params = render_params(spec["params"], symbol=symbol, window_days=window_days)
    rows = await client.get(spec["endpoint"], params=params)        # 端點也讀自 yaml
    features, feature_report = compute_series_features(
        "funding_rate", spec, series,
        expected_count=window_days * int(spec["samples_per_day"]),
        provided={"crowd_label": crowd_label(percentile)},          # 端點自己算的欄位
    )

    card, card_report = build_evidence_card(
        factor_id, evidence_id=_evidence_id(factor_id, coin),
        stage2=stage2, knowledge=knowledge,
        evidence_weight=stage4["final_evidence_weight"],
        features=stage2.get("features"),
    )

自我檢查（不用啟動 server、不碰任何網路）：
    python -m webapp.stage_specs
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import yaml

from agent.collectors.derivatives import percentile_rank

# webapp/stage_specs.py -> webapp -> HOYAbit_ai_agent/
_ROOT = Path(__file__).resolve().parent.parent

FEATURE_DIR = _ROOT / "Stage 2 — Feature Extraction"
WEIGHT_DIR = _ROOT / "Stage 4 — Dynamic Evidence Weight Engine"
CARD_DIR = _ROOT / "Stage 5 — Evidence Card ＋ Prioritization"

# Stage 4 的 prior_weight 認得的兩種尺（2026-08-02 拍板）：
#   raw_ic            → 值是相關係數原值，排序前要先換算（取絕對值→樣本收縮→映射）
#   relative_strength → 值已經是 [0,1] 的 IC 等價強度，直接用
# 換算完成後全部都是 relative_strength，這樣排序才是拿同一個量在比大小。
KNOWN_PRIOR_SCALES = {"raw_ic", "relative_strength"}


class SpecError(RuntimeError):
    """規格檔讀不到／解析不了／參數樣板看不懂時拋出。

    刻意不吞掉這類錯誤退回預設值——規格檔是單一事實來源，讀不到就該吵，
    不然會退化成「程式又自己用寫死的值跑起來了」，就是這支模組要解決的問題本身。"""


# ---------------------------------------------------------------------------
# 讀檔
# ---------------------------------------------------------------------------

_YAML_BLOCK = re.compile(r"```yaml\n(.*?)\n```", re.DOTALL)


def _parse_yaml(text: str, path: Path) -> dict:
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SpecError(f"{path.name} 的 yaml 解析失敗：{exc}") from exc
    if not isinstance(parsed, dict):
        raise SpecError(f"{path.name} 的 yaml 頂層不是 mapping")
    return parsed


def load_feature_spec(factor_id: str) -> dict:
    """讀 `Stage 2 — Feature Extraction/{factor_id}.yaml` 的 `feature:` 區塊。"""
    path = FEATURE_DIR / f"{factor_id}.yaml"
    if not path.exists():
        raise SpecError(f"找不到 Stage 2 規格檔：{path}")
    parsed = _parse_yaml(path.read_text(encoding="utf-8"), path)
    feature = parsed.get("feature")
    if not isinstance(feature, dict):
        raise SpecError(f"{path.name} 缺少 `feature:` 區塊")
    return feature


def load_value_source(factor_id: str) -> dict | None:
    """讀 Stage 2 yaml 的 `value_source:` 區塊，沒有就回 None。

    只有 Event Factor 會有這一段。cpi 的 `feature:` 是 Event 骨架（事件何時公布、
    幾個來源確認），裡面沒有「這次公布的數字」跟抓數字的端點——但 Stage 5 cpi.md
    的 fact 要 current_value／mom_pct／yoy_pct／percentile。`value_source` 就是補這格，
    刻意跟 `feature:` 分開放，免得把 2026-08-02「CPI 是 Event 不是 Statistical」的
    重新分類又混回去。Statistical factor 沒有這一段（它們的端點就在 `feature.endpoint`）。"""
    path = FEATURE_DIR / f"{factor_id}.yaml"
    if not path.exists():
        raise SpecError(f"找不到 Stage 2 規格檔：{path}")
    parsed = _parse_yaml(path.read_text(encoding="utf-8"), path)
    source = parsed.get("value_source")
    if source is None:
        return None
    if not isinstance(source, dict):
        raise SpecError(f"{path.name} 的 `value_source:` 不是 mapping")
    return source


def load_card_spec(factor_id: str) -> dict:
    """讀 `Stage 5 — Evidence Card ＋ Prioritization/{factor_id}.md` 的 yaml 區塊。

    回傳整份（含 `evidence` 與 `prioritization` 兩塊）。"""
    path = CARD_DIR / f"{factor_id}.md"
    if not path.exists():
        raise SpecError(f"找不到 Stage 5 卡片規格檔：{path}")
    match = _YAML_BLOCK.search(path.read_text(encoding="utf-8"))
    if not match:
        raise SpecError(f"{path.name} 找不到 ```yaml 區塊")
    parsed = _parse_yaml(match.group(1), path)
    if not isinstance(parsed.get("evidence"), dict):
        raise SpecError(f"{path.name} 缺少 `evidence:` 區塊")
    return parsed


def feature_spec_file(factor_id: str) -> str:
    return f"Stage 2 — Feature Extraction/{factor_id}.yaml"


def card_spec_file(factor_id: str) -> str:
    return f"Stage 5 — Evidence Card ＋ Prioritization/{factor_id}.md"


# ---------------------------------------------------------------------------
# 查詢參數：把 yaml 的 params 樣板套上這次執行的實際值
# ---------------------------------------------------------------------------

# 只認這幾種樣板寫法，看不懂就拋 SpecError——不做「猜猜看」的寬鬆解析。
#   {symbol}        → 這次查詢的交易對（BTCUSDT）
#   {window}        → LLM 依 Horizon 判斷出的窗口天數
#   {window}days    → 同上，直接接在字串裡（blockchain.info 的 timespan 就長這樣）
#   {window * 3}    → 窗口天數 × 每天筆數（funding rate 每 8 小時一筆）
_PLACEHOLDER = re.compile(r"\{\s*(\w+)\s*(?:\*\s*(\d+)\s*)?\}")


def render_params(
    params: dict | None,
    *,
    symbol: str | None = None,
    window_days: int | None = None,
) -> dict[str, str]:
    """把 yaml `params:` 的樣板換成這次執行的實際值，回傳可直接丟給 httpx 的 dict。"""
    if not params:
        return {}
    values: dict[str, int | str | None] = {"symbol": symbol, "window": window_days}
    rendered: dict[str, str] = {}

    for key, raw in params.items():
        if isinstance(raw, bool):
            rendered[key] = "true" if raw else "false"
            continue
        if not isinstance(raw, str):
            rendered[key] = str(raw)
            continue

        def _sub(match: re.Match) -> str:
            name, factor = match.group(1), match.group(2)
            if name not in values:
                raise SpecError(f"params.{key} 用了看不懂的樣板 `{match.group(0)}`（可用：symbol／window）")
            value = values[name]
            if value is None:
                raise SpecError(f"params.{key} 需要 {name}，但這次呼叫沒有提供")
            if factor:
                if not isinstance(value, int):
                    raise SpecError(f"params.{key} 對非數值 {name} 做乘法")
                return str(value * int(factor))
            return str(value)

        rendered[key] = _PLACEHOLDER.sub(_sub, raw)

    return rendered


# ---------------------------------------------------------------------------
# Stage 2：照 yaml 的欄位清單算 features
# ---------------------------------------------------------------------------

# yaml 的 meta 欄位，不是要算的 feature
_META_FIELDS = {"factor", "endpoint", "params", "samples_per_day"}

# 判斷 yaml 那格寫的是「公式（要算）」還是「值（直接用）」。
# Statistical 骨架的每一格都是公式字串（`series[-1]`／`mean(series)`／`percentile_rank(...)`）；
# Event 骨架（cpi.yaml）不一樣——它的 announcement_time／confirmation_count／next_release
# 本身就是這個 factor 的事實資料，規格檔就是資料來源，照抄即可，不需要也沒得算。
_FORMULA_TOKENS = ("series", "window", "len(", "(", "[")


def _looks_like_formula(value: object) -> bool:
    if not isinstance(value, str):
        return False
    return any(token in value for token in _FORMULA_TOKENS)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _pstd(xs: list[float]) -> float:
    m = _mean(xs)
    return (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5


def _lsq_slope(xs: list[float]) -> float | None:
    """最小平方法斜率（x 軸＝樣本序號 0..n-1）。少於 2 筆算不出來。"""
    n = len(xs)
    if n < 2:
        return None
    mean_i = (n - 1) / 2
    mean_y = _mean(xs)
    denom = sum((i - mean_i) ** 2 for i in range(n))
    if denom == 0:
        return None
    return sum((i - mean_i) * (y - mean_y) for i, y in enumerate(xs)) / denom


def _nth_back(series: list[float], steps: int) -> float | None:
    """往回數 steps 筆（steps=1 → 前一筆）。不夠長回 None。"""
    idx = len(series) - 1 - steps
    return series[idx] if idx >= 0 else None


def _roc(series: list[float], steps: int) -> float | None:
    base = _nth_back(series, steps)
    if base in (None, 0):
        return None
    return (series[-1] - base) / base * 100


def _round(value: float | None, sig: int = 6) -> float | None:
    """四捨五入到 `sig` 位有效數字，不是固定小數位。

    這裡不能用 `round(x, 6)`：funding rate 的值本身量級是 1e-5，斜率是 1e-8，
    固定 6 位小數會把整排 slope 壓成 0.0，看起來像「趨勢是平的」——那是顯示造成的
    假結論，不是資料。active_address 的值是 6 位數，同一套固定小數位又嫌太細。
    兩個 factor 的量級差 10 個數量級，只有有效數字這種相對精度接得住。"""
    if value is None or value == 0 or not math.isfinite(value):
        return value
    exponent = math.floor(math.log10(abs(value)))
    return round(value, -(exponent - sig + 1))


def compute_series_features(
    factor_id: str,
    spec: dict,
    series: list[float],
    *,
    samples_per_day: int | None = None,
    expected_count: int | None = None,
    provided: dict | None = None,
) -> tuple[dict, dict]:
    """照 yaml 定義的欄位清單算出 features，回傳 (features, report)。

    - yaml 值是公式字串 → 照欄位名對到本檔的同名算法算（公式字串本身不被執行）
    - yaml 值是 `null`  → 結構性不存在，不產生這個 key（liquidation 一整排 slope/roc/rolling_*）
    - 樣本不夠算（例如 window 只有 3 天卻要 roc_7d）→ 值給 None，並列進 fields_insufficient_data
    - 端點自己算的欄位（liquidation 的 observed_count、funding 的 crowd_label）用 provided 傳進來
    - yaml 有定義、但這裡跟端點都沒實作 → 列進 fields_unimplemented，不靜靜漏掉

    `samples_per_day` 是「近 N 天」類欄位的換算係數：funding rate 每 8 小時一筆＝3，
    日頻 factor＝1。沒傳就讀 yaml 的 `samples_per_day`，再沒有就當 1。"""
    spd = samples_per_day or int(spec.get("samples_per_day", 1) or 1)
    provided = provided or {}

    computers = {
        "current_value": lambda: series[-1] if series else None,
        "previous_value": lambda: _nth_back(series, 1),
        "delta": lambda: (series[-1] - _nth_back(series, 1)) if _nth_back(series, 1) is not None else None,
        "percentile": lambda: percentile_rank(series[-1], series) if series else None,
        "z_score": lambda: ((series[-1] - _mean(series)) / _pstd(series)) if len(series) > 1 and _pstd(series) else None,
        "slope": lambda: _lsq_slope(series[-3:]),
        "slope_7d": lambda: _lsq_slope(series[-7 * spd:]),
        "slope_30d": lambda: _lsq_slope(series),
        "roc_1d": lambda: _roc(series, spd),
        "roc_7d": lambda: _roc(series, 7 * spd),
        # 月頻序列用（cpi 的 value_source）：mom＝跟前一期比。
        # yoy 要往回 13 期、通常超出這次的窗口，所以固定由呼叫端拿完整序列算完用
        # provided 帶進來（cpi.yaml 的 yoy_pct 那行已標明「固定用完整序列算」）
        "mom_pct": lambda: _roc(series, 1),
        "rolling_mean": lambda: _mean(series) if series else None,
        "rolling_std": lambda: _pstd(series) if series else None,
        "rolling_max": lambda: max(series) if series else None,
        "rolling_min": lambda: min(series) if series else None,
        "sample_size": lambda: len(series),
        # 沒有 expected_count（＝這次「應該」拿到幾筆）就算不出缺漏比例，值給 None
        # 落進 fields_insufficient_data；那是呼叫端沒給參數，不是這個欄位沒實作
        "missing_ratio": lambda: max(0.0, 1 - len(series) / expected_count) if expected_count else None,
    }

    features: dict = {}
    defined: list[str] = []
    computed: list[str] = []
    literal: list[str] = []
    null_by_design: list[str] = []
    insufficient: list[str] = []
    unimplemented: list[str] = []

    for name, formula in spec.items():
        if name in _META_FIELDS:
            continue
        defined.append(name)

        if name in provided:
            features[name] = provided[name]
            computed.append(name)
            continue

        if formula is None:
            # yaml 明寫 null＝這個 factor 結構性沒有這個概念，整格不產生（不塞 None
            # 假裝「這次剛好沒算出來」）——liquidation.yaml 的 slope／roc／rolling_* 就是這樣
            null_by_design.append(name)
            continue

        if not isinstance(formula, str):
            # 規格檔寫的是「值」不是公式（數字／字典），照抄。這一條要**排在算法前面**：
            # liquidation.yaml 明寫 `sample_size: 1`（每次執行只有一個觀察窗，不是多筆
            # 歷史樣本），若讓通用的 len(series) 算法先跑會算出 0，蓋掉規格檔的宣告。
            # 反過來 active_address.yaml 寫的是 `sample_size: len(series)`——同一個欄位名，
            # 一個宣告值、一個宣告算法，差別就在規格檔怎麼寫
            features[name] = formula
            literal.append(name)
            continue

        fn = computers.get(name)
        if fn is None:
            if _looks_like_formula(formula):
                # 是公式，但這裡沒有對應算法（例如 funding_rate 的 crowd_label 由端點補、
                # liquidation 的 observed_count 由 WebSocket 端點補）。沒被 provided
                # 帶進來就是真的沒實作，如實列出來
                unimplemented.append(name)
            else:
                # 純文字敘述（Event 骨架的 announcement_time／event_type 之類），照抄
                features[name] = formula
                literal.append(name)
            continue

        value = fn()
        if value is None:
            insufficient.append(name)
        else:
            computed.append(name)
        features[name] = _round(value) if isinstance(value, float) else value

    report = {
        "source_file": feature_spec_file(factor_id),
        "samples_per_day": spd,
        "fields_defined": defined,
        "fields_computed": computed,
        "fields_from_spec_literal": literal,
        "fields_null_by_design": null_by_design,
        "fields_insufficient_data": insufficient,
        "fields_unimplemented": unimplemented,
    }
    return features, report


def pct_change_vs_month(
    dated_series: list[tuple[str, float]], months_back: int = 12
) -> tuple[float | None, str]:
    """月頻序列的「跟 N 個月前比」變化率，**用日期對齊，不用位置索引**。

    為什麼不能用 `series[-13]`：FRED 的 CPIAUCSL 實際上會缺月（2026-08-02 抓下來的
    序列就缺 2025-10，2025-09 直接跳到 2025-11）。缺一個月，位置索引就整個位移一格——
    最新值是 2026-06 時，`series[-13]` 拿到的是 2025-05 而不是 2025-06，年增率算成
    3.73%，正確值是 3.46%（Stage 3 cpi.md 手動查證那筆 3.464 是對的）。
    數字看起來很合理、不會報錯，所以這種錯不靠對照根本看不出來。

    回傳 (變化率, 說明)。目標月份不在序列裡就回 (None, 原因)——不退而求其次拿
    鄰近月份頂替，那只會把同一種錯誤換個形式留下來。"""
    if not dated_series:
        return None, "序列是空的"

    last_date, last_value = dated_series[-1]
    try:
        year, month = int(last_date[:4]), int(last_date[5:7])
    except (ValueError, IndexError):
        return None, f"最新一筆的日期格式看不懂：{last_date}"

    total = year * 12 + (month - 1) - months_back
    target = f"{total // 12:04d}-{total % 12 + 1:02d}"

    for date, value in reversed(dated_series):
        if date.startswith(target):
            if value == 0:
                return None, f"{target} 的值是 0，算不出變化率"
            return (last_value - value) / value * 100, f"{last_date[:7]} vs {target}（日期對齊）"

    return None, f"序列裡沒有 {target} 這個月（資料源缺月），不用鄰近月份頂替"


# ---------------------------------------------------------------------------
# Stage 5：照卡片 .md 的 schema 組裝 Evidence Card
# ---------------------------------------------------------------------------

# Stage 2 輸出的鍵名跟卡片 fact 格子名對不上的少數例外。
# funding_rate 的 Stage 2 回應把最新費率放在 `funding`（帶 % 格式），卡片那格叫
# current_value——這種名字差異寫在這裡一目了然，不要散在各處的 if。
_FACT_ALIASES = {
    "funding_rate": {"current_value": "funding"},
    # 卡片那格叫 sentiment_score_overall（強調它是整段窗口的平均，不是單篇分數），
    # Stage 2 輸出的鍵名是 sentiment_score
    "panews_sentiment": {"sentiment_score_overall": "sentiment_score"},
}

# 卡片 .md 用 `→ 欄位名` 表示「這格在這一型 Knowledge 裡不叫這個名字，對應過去」
# （cpi 的 primary_horizon → reaction_window）。不是等價替換，所以要在輸出裡標明。
_MAPPING_PREFIX = "→"


def _fact_value(factor_id: str, key: str, stage2: dict, features: dict | None) -> object:
    alias = _FACT_ALIASES.get(factor_id, {}).get(key, key)
    if alias in stage2:
        return stage2[alias]
    if features and alias in features:
        return features[alias]
    return None


def build_evidence_card(
    factor_id: str,
    *,
    evidence_id: str,
    stage2: dict,
    knowledge: dict,
    evidence_weight: float | None,
    features: dict | None = None,
    runtime_values: dict | None = None,
) -> tuple[dict, dict]:
    """照 `Stage 5 — .../{factor_id}.md` 的 evidence schema 組裝卡片。

    卡片有哪些格子、fact 有哪些欄位、哪一格是對應欄位，全部由那份 .md 決定；
    值來自這次執行的 Stage 2/3/4 輸出。回傳 (card, report)。

    liquidation 的 fact 刻意沒有 percentile／trend 兩個 key（不是放 null），
    cpi 的 primary_horizon 對應到 Event Knowledge 的 reaction_window——這兩件事
    現在都是讀檔讀出來的，不是程式裡的 if。

    `runtime_values` 放執行期才算得出來、卡片檔不會有的值（例如 confidence）。

    ⚠️ 卡片 schema 有、但這次沒有任何來源填得出來的格子（例如 panews 的 persistence——
    Stage 3 那份根本沒有這個欄位）**整格不產生，不留 null**（2026-08-02 Ken 拍板）。
    理由跟 liquidation 的 fact 不放 percentile 是同一條：留 null 會被下游讀成
    「這次剛好沒算出來，下次可能有」，整格不存在才傳達得出「這個 factor 沒有這個東西」。
    這些格子仍然會列在回傳的 report `unresolved_fields` 裡，不是靜靜消失。"""
    spec = load_card_spec(factor_id)
    evidence_spec: dict = spec["evidence"]

    card: dict = {}
    mapped: dict[str, str] = {}
    unresolved: list[str] = []

    for key, spec_value in evidence_spec.items():
        if key == "evidence_id":
            card[key] = evidence_id
        elif key == "category":
            card[key] = knowledge.get("category")
        elif key == "fact":
            fact_keys = list(spec_value or {})
            card[key] = {k: _fact_value(factor_id, k, stage2, features) for k in fact_keys}
        elif key == "features":
            card[key] = stage2
        elif key == "knowledge":
            card[key] = knowledge
        elif key == "evidence_weight":
            card[key] = evidence_weight
        elif key in ("source_reliability", "historical_support"):
            # 卡片 .md 明寫 null：Stage 4 這兩項仍是註解狀態，跟著留白，
            # 不在 Stage 5 重複造一套新標準
            card[key] = None
        elif key == "related_evidence":
            sub_keys = list(spec_value or {}) or ["confirms", "conflicts", "independent"]
            card[key] = {k: knowledge.get(k) for k in sub_keys}
        elif key == "traceability":
            if isinstance(spec_value, dict):
                # 目前只有 liquidation 是這種形狀：note 是 Stage 2 liquidation.yaml
                # 的「降級處理」條款指定要寫在卡片上的內容，屬於規格檔的內容本身，
                # 所以直接照抄 .md，不是程式自己生成的字
                card[key] = {"source": stage2.get("source"), "note": spec_value.get("note")}
            else:
                card[key] = stage2.get("source")
        elif isinstance(spec_value, str) and spec_value.strip().startswith(_MAPPING_PREFIX):
            target = spec_value.strip().lstrip(_MAPPING_PREFIX).strip()
            card[key] = knowledge.get(target)
            mapped[key] = target
        elif (runtime_values or {}).get(key) is not None:
            card[key] = runtime_values[key]
        elif key in knowledge:
            card[key] = knowledge[key]
        else:
            # 卡片 schema 有這格，但這次沒有任何來源填得出來（panews 的 persistence：
            # Stage 3 那份沒有這個欄位）。2026-08-02 Ken 拍板**整格不產生**——留 null
            # 會被讀成「這次剛好沒算出來」。仍然列進 report，不是靜靜消失
            unresolved.append(key)

    report = {
        "source_file": card_spec_file(factor_id),
        "fields_from_spec": list(evidence_spec.keys()),
        "mapped_fields": mapped,
        "unresolved_fields": unresolved,
        "ranking_key": (spec.get("prioritization") or {}).get("ranking_key"),
        # 2026-08-02 補充拍板：排序鍵不變，比大小時取絕對值（ic 是相關係數，
        # 負值是反向訊號不是弱訊號）。這格讓排序層驗證得了「卡片自己怎麼說」
        "ranking_transform": (spec.get("prioritization") or {}).get("ranking_transform"),
    }
    return card, report


def ranking_keys() -> dict[str, str | None]:
    """把每張卡各自 .md 裡寫的 ranking_key 讀出來，讓排序那層可以驗證「大家真的都照
    evidence_weight 排」，而不是程式自己寫死一個字串就宣稱符合 13 的拍板。"""
    keys: dict[str, str | None] = {}
    for path in sorted(CARD_DIR.glob("*.md")):
        factor_id = path.stem
        try:
            spec = load_card_spec(factor_id)
        except SpecError:
            keys[factor_id] = None
            continue
        keys[factor_id] = (spec.get("prioritization") or {}).get("ranking_key")
    return keys


def prior_weight_scales() -> dict[str, dict]:
    """把 Stage 4 各份 .md 的 `prior_weight` 讀出來，檢查「值在哪把尺上」有沒有宣告。

    為什麼要查：2026-08-02 之前踩過一次——有一份 .md 自己套了正規化公式把 ic 變成
    0.755，還註明「沿用跟 cpi/liquidation 一致的公式」，但那兩份根本沒套公式。
    當時沒有任何機制會發現「六個 factor 的 prior_weight 不在同一把尺上」，是人工
    比對才抓到的。這支就是把那次的人工比對變成每次都會跑的檢查。

    沒有 `prior_weight.value` 的 factor（例如 funding_rate／active_address，ic 每次
    現場算）不算缺漏——它們的值不經過 .md，程式算完直接套全域換算，沒有「宣告錯尺」
    的空間。"""
    scales: dict[str, dict] = {}
    if not WEIGHT_DIR.exists():
        return scales
    for path in sorted(WEIGHT_DIR.glob("*.md")):
        factor_id = path.stem
        match = _YAML_BLOCK.search(path.read_text(encoding="utf-8"))
        if not match:
            scales[factor_id] = {"declared": None, "has_value": False, "error": "找不到 ```yaml 區塊"}
            continue
        try:
            parsed = _parse_yaml(match.group(1), path)
        except SpecError as exc:
            scales[factor_id] = {"declared": None, "has_value": False, "error": str(exc)}
            continue
        prior = ((parsed.get("weight") or {}).get("prior_weight")) or {}
        scales[factor_id] = {
            "declared": prior.get("scale"),
            "has_value": prior.get("value") is not None,
            "basis": prior.get("basis"),
            "error": None,
        }
    return scales


def ranking_transforms() -> dict[str, str | None]:
    """2026-08-02 Ken 補充拍板：排序鍵不變（evidence_weight），但比大小時取絕對值。
    這是「怎麼比」不是「比什麼」，所以獨立成 `ranking_transform` 一格，而不是把
    ranking_key 改寫成 "abs(evidence_weight)" ——ranking_key 講的是排序讀哪個欄位，
    那件事沒有變。兩格都讀出來，排序層才驗證得了自己有沒有照卡片宣告的方式排。"""
    transforms: dict[str, str | None] = {}
    for path in sorted(CARD_DIR.glob("*.md")):
        factor_id = path.stem
        try:
            spec = load_card_spec(factor_id)
        except SpecError:
            transforms[factor_id] = None
            continue
        transforms[factor_id] = (spec.get("prioritization") or {}).get("ranking_transform")
    return transforms


# ---------------------------------------------------------------------------
# 自我檢查：python -m webapp.stage_specs
# ---------------------------------------------------------------------------

def _selfcheck() -> int:
    factors = sorted(p.stem for p in FEATURE_DIR.glob("*.yaml"))
    problems: list[str] = []

    print("=" * 78)
    print("Stage 2 — Feature Extraction（規格檔 → 欄位清單）")
    print("=" * 78)
    for factor_id in factors:
        try:
            spec = load_feature_spec(factor_id)
        except SpecError as exc:
            problems.append(f"[Stage 2] {factor_id}: {exc}")
            print(f"\n✗ {factor_id}: {exc}")
            continue

        # 用一段合成序列（不打網路）檢查欄位分類，值本身不重要
        series = [1.0 + 0.1 * i for i in range(45)]
        spd = int(spec.get("samples_per_day", 1) or 1)
        features, report = compute_series_features(
            factor_id, spec, series, expected_count=45 * spd
        )
        print(f"\n● {factor_id}  （endpoint: {spec.get('endpoint') or '（無，非抓取型）'}）")
        print(f"   samples_per_day = {report['samples_per_day']}")
        print(f"   定義 {len(report['fields_defined'])} 格 ／ 算得出 {len(report['fields_computed'])}")
        if report["fields_from_spec_literal"]:
            print(f"   規格檔即資料（照抄）: {', '.join(report['fields_from_spec_literal'])}")
        if report["fields_null_by_design"]:
            print(f"   結構性 null（不產生 key）: {', '.join(report['fields_null_by_design'])}")
        if report["fields_insufficient_data"]:
            print(f"   樣本不足: {', '.join(report['fields_insufficient_data'])}")
        if report["fields_unimplemented"]:
            print(f"   ⚠ yaml 有定義但未實作: {', '.join(report['fields_unimplemented'])}")

        params = spec.get("params")
        if params:
            try:
                print(f"   params 套用 (symbol=BTCUSDT, window=14) → {render_params(params, symbol='BTCUSDT', window_days=14)}")
            except SpecError as exc:
                problems.append(f"[Stage 2 params] {factor_id}: {exc}")
                print(f"   ✗ params 樣板套用失敗：{exc}")

    print()
    print("=" * 78)
    print("Stage 5 — Evidence Card（規格檔 → 卡片格子）")
    print("=" * 78)
    stub_stage2 = {
        "source": "（stub）",
        "funding": "+0.0100%",
        "current_value": "123",
        "percentile": "80th",
        "trend": "Increasing",
        "mom_pct": "+0.10%",
        "yoy_pct": "+3.00%",
        "observed_count": 0,
        "observed_notional": "0.00",
        "listen_seconds": 6,
    }
    stub_knowledge = {
        "category": "statistical",
        "primary_horizon": "短期",
        "persistence": "中",
        "reaction_window": "公布當下至 2-3 個交易日",
        "expected_duration": "數週至數月",
        "confirms": "open_interest",
        "conflicts": None,
        "independent": "cpi",
    }
    for path in sorted(CARD_DIR.glob("*.md")):
        factor_id = path.stem
        try:
            card, report = build_evidence_card(
                factor_id,
                evidence_id=f"{factor_id.upper()}_BTC",
                stage2=stub_stage2,
                knowledge=stub_knowledge,
                evidence_weight=0.5,
            )
        except SpecError as exc:
            problems.append(f"[Stage 5] {factor_id}: {exc}")
            print(f"\n✗ {factor_id}: {exc}")
            continue
        print(f"\n● {factor_id}  （ranking_key: {report['ranking_key']}）")
        print(f"   卡片格子: {', '.join(report['fields_from_spec'])}")
        print(f"   fact 欄位: {', '.join(card['fact'])}")
        if report["mapped_fields"]:
            print(f"   對應欄位（非原欄位）: {report['mapped_fields']}")
        if report["unresolved_fields"]:
            print(f"   ⚠ schema 有、這次填不出來: {', '.join(report['unresolved_fields'])}")

    print()
    print("=" * 78)
    keys = ranking_keys()
    print(f"排序鍵（各卡 .md 的 prioritization.ranking_key）：{keys}")
    missing = [f for f, v in keys.items() if v is None]
    wrong = {f: v for f, v in keys.items() if v is not None and v != "evidence_weight"}
    if missing:
        problems.append(f"[排序] 這幾張卡的 .md 沒有 prioritization.ranking_key：{', '.join(missing)}")
        print(f"⚠ 沒寫 ranking_key：{', '.join(missing)}——13 拍板一律照 evidence_weight，卡片沒宣告就無從驗證")
    if wrong:
        problems.append(f"[排序] 卡片 .md 的 ranking_key 跟 13 拍板不一致：{wrong}")
        print(f"⚠ 不是 evidence_weight：{wrong}")

    transforms = ranking_transforms()
    print(f"排序轉換（各卡 .md 的 prioritization.ranking_transform）：{transforms}")
    missing_tf = [f for f, v in transforms.items() if v is None]
    wrong_tf = {f: v for f, v in transforms.items() if v is not None and v != "abs"}
    if missing_tf:
        problems.append(f"[排序] 這幾張卡的 .md 沒有 prioritization.ranking_transform：{', '.join(missing_tf)}")
        print(
            f"⚠ 沒寫 ranking_transform：{', '.join(missing_tf)}"
            "——2026-08-02 拍板比大小時取絕對值，卡片沒宣告就無從驗證"
        )
    if wrong_tf:
        # 這裡不是「只准填 abs」的教條：一張卡如果真的要用別的轉換，先去 13 拍板，
        # 拍完連同這個檢查一起改。混用（有的 abs、有的不是）才是真正會出事的狀態——
        # 同一次排序裡兩張卡用不同尺度比大小，名次就沒有意義了。
        problems.append(f"[排序] 卡片 .md 的 ranking_transform 跟 13 拍板不一致：{wrong_tf}")
        print(f"⚠ 不是 abs：{wrong_tf}")

    print()
    scales = prior_weight_scales()
    shown = {f: v["declared"] for f, v in scales.items()}
    print(f"Prior Weight 的尺（各 Stage 4 .md 的 prior_weight.scale）：{shown}")
    for factor_id, info in scales.items():
        if info.get("error"):
            problems.append(f"[Stage 4] {factor_id}.md 讀不起來：{info['error']}")
            print(f"⚠ {factor_id}: {info['error']}")
            continue
        if not info["has_value"]:
            # 值不經過 .md（ic 每次現場算），沒有宣告錯尺的空間，不算缺漏
            print(f"   {factor_id}: 無 prior_weight.value（現場計算），不需宣告 scale")
            continue
        declared = info["declared"]
        if declared is None:
            problems.append(f"[Stage 4] {factor_id}.md 的 prior_weight 沒宣告 scale（raw_ic / relative_strength）")
            print(f"⚠ {factor_id}: 有 value 卻沒宣告 scale——排序層無從知道這個數字要不要換算")
        elif declared not in KNOWN_PRIOR_SCALES:
            problems.append(f"[Stage 4] {factor_id}.md 的 scale 不認得：{declared}")
            print(f"⚠ {factor_id}: scale={declared} 不在 {sorted(KNOWN_PRIOR_SCALES)} 裡")

    print()
    if problems:
        print(f"✗ {len(problems)} 個問題：")
        for p in problems:
            print(f"   - {p}")
        return 1
    print("✓ 所有規格檔都讀得起來、欄位分類正常")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selfcheck())
