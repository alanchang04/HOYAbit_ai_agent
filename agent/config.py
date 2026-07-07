"""環境設定載入與 API key 存在性檢查。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    # --- Bedrock ---
    aws_region: str = field(default_factory=lambda: os.getenv("AWS_REGION", "us-east-1"))
    bedrock_model_id: str = field(
        default_factory=lambda: os.getenv(
            "BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"
        )
    )

    # --- 選用 API keys（缺少時該 collector 會退回免 key 端點或標記 skipped）---
    cryptopanic_api_key: str | None = field(default_factory=lambda: os.getenv("CRYPTOPANIC_API_KEY"))
    etherscan_api_key: str | None = field(default_factory=lambda: os.getenv("ETHERSCAN_API_KEY"))
    bscscan_api_key: str | None = field(default_factory=lambda: os.getenv("BSCSCAN_API_KEY"))
    fred_api_key: str | None = field(default_factory=lambda: os.getenv("FRED_API_KEY"))

    # --- 執行時間控制 ---
    hard_deadline_seconds: int = field(
        default_factory=lambda: int(os.getenv("HARD_DEADLINE_SECONDS", "900"))
    )
    degraded_mode_trigger_seconds: int = field(
        default_factory=lambda: int(os.getenv("DEGRADED_MODE_TRIGGER_SECONDS", "720"))
    )
    collector_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("COLLECTOR_TIMEOUT_SECONDS", "75"))
    )

    data_dir: str = field(default_factory=lambda: os.getenv("DATA_DIR", "data"))
    output_dir: str = field(default_factory=lambda: os.getenv("OUTPUT_DIR", "output"))


OPTIONAL_KEY_NAMES = {
    "CRYPTOPANIC_API_KEY": "news_collector 的 CryptoPanic 補充來源（缺少時僅用 RSS 免 key 來源）",
    "ETHERSCAN_API_KEY": "onchain_collector 的 ETH 鏈上資料（缺少時該來源會被跳過並記為 skipped）",
    "BSCSCAN_API_KEY": "onchain_collector 的 BNB 鏈上資料（缺少時該來源會被跳過並記為 skipped）",
    "FRED_API_KEY": "macro_collector 的 FRED 總經加強資料（缺少時僅用 stooq/Fear&Greed 免 key 來源）",
}


def check_optional_keys() -> list[str]:
    """回傳缺少的選用 API key 警告訊息清單（供啟動時印出）。"""
    warnings = []
    for env_name, description in OPTIONAL_KEY_NAMES.items():
        if not os.getenv(env_name):
            warnings.append(f"[WARN] 未設定 {env_name}：{description}")
    return warnings


def get_settings() -> Settings:
    return Settings()
