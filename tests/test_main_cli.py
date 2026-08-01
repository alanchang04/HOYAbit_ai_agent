"""CLI 進入點（main.py）的 --output-dir 預設行為：v1.2 起未指定時要給每次執行
一個獨立的 run id 子目錄，不再落回固定的 output/ 而覆蓋上一次的紀錄。
"""

from unittest.mock import patch

import main


def _fake_run_pipeline(**kwargs):
    from dataclasses import dataclass

    @dataclass
    class _FakeResult:
        elapsed_seconds: float = 1.23
        degraded_mode: bool = False
        evidences: list = None

        def __post_init__(self):
            if self.evidences is None:
                self.evidences = []

    _fake_run_pipeline.captured_kwargs = kwargs
    return _FakeResult()


class TestOutputDirDefaulting:
    def test_no_output_dir_generates_unique_cli_runs_subdir(self):
        with patch("main.run_pipeline", side_effect=_fake_run_pipeline) as mock_run:
            main.main(["--coin", "BTC", "--question", "分析 BTC", "--dry-run"])

        output_dir = mock_run.call_args.kwargs["output_dir"]
        assert output_dir is not None
        assert output_dir.replace("\\", "/").startswith("output/cli_runs/")

    def test_two_runs_without_output_dir_get_different_subdirs(self):
        with patch("main.run_pipeline", side_effect=_fake_run_pipeline) as mock_run:
            main.main(["--coin", "BTC", "--question", "分析 BTC", "--dry-run"])
            first = mock_run.call_args.kwargs["output_dir"]
            main.main(["--coin", "BTC", "--question", "分析 BTC", "--dry-run"])
            second = mock_run.call_args.kwargs["output_dir"]

        assert first != second

    def test_explicit_output_dir_is_respected_unchanged(self):
        with patch("main.run_pipeline", side_effect=_fake_run_pipeline) as mock_run:
            main.main(
                ["--coin", "BTC", "--question", "分析 BTC", "--dry-run", "--output-dir", "output/my_custom_dir"]
            )

        assert mock_run.call_args.kwargs["output_dir"] == "output/my_custom_dir"
