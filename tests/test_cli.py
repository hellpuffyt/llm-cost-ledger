import json
from pathlib import Path

import pytest

from llm_cost_ledger.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
OPENAI_EXPORT = EXAMPLES / "openai_usage.json"
ANTHROPIC_EXPORT = EXAMPLES / "anthropic_usage.csv"
MAPPING = EXAMPLES / "mapping.yaml"
DRIFT_EXPORT = EXAMPLES / "drift_usage.csv"
CUSTOM_PRICING = EXAMPLES / "custom_pricing.yaml"


def test_ingest_writes_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["ingest", "--input", f"openai={OPENAI_EXPORT}"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert len(payload) == 8
    assert payload[0]["provider"] == "openai"


def test_report_table_output(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "report",
            "--input",
            f"openai={OPENAI_EXPORT}",
            "--input",
            f"anthropic={ANTHROPIC_EXPORT}",
            "--mapping",
            str(MAPPING),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "TOTAL" in out
    assert "marketing" in out
    assert "engineering" in out


def test_report_json_output_is_valid(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "report",
            "--input",
            f"openai={OPENAI_EXPORT}",
            "--format",
            "json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert payload[0]["cost_usd"] > 0


def test_report_csv_output(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["report", "--input", f"openai={OPENAI_EXPORT}", "--format", "csv"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cost_usd" in out.splitlines()[0]


def test_report_writes_to_output_file(tmp_path: Path) -> None:
    out_path = tmp_path / "report.json"
    rc = main(
        [
            "report",
            "--input",
            f"openai={OPENAI_EXPORT}",
            "--format",
            "json",
            "--output",
            str(out_path),
        ]
    )
    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload


def test_report_max_cost_gate_passes_when_under_limit() -> None:
    rc = main(
        [
            "report",
            "--input",
            f"openai={OPENAI_EXPORT}",
            "--max-cost-per-request",
            "1000",
        ]
    )
    assert rc == 0


def test_report_max_cost_gate_fails_when_over_limit() -> None:
    rc = main(
        [
            "report",
            "--input",
            f"openai={OPENAI_EXPORT}",
            "--max-cost-per-request",
            "0.0000001",
        ]
    )
    assert rc == 2


def test_report_custom_pricing_changes_cost(capsys: pytest.CaptureFixture[str]) -> None:
    main(["report", "--input", f"openai={OPENAI_EXPORT}", "--format", "json"])
    default_payload = json.loads(capsys.readouterr().out)
    default_total = sum(row["cost_usd"] for row in default_payload)

    main(
        [
            "report",
            "--input",
            f"openai={OPENAI_EXPORT}",
            "--format",
            "json",
            "--pricing",
            str(CUSTOM_PRICING),
        ]
    )
    custom_payload = json.loads(capsys.readouterr().out)
    custom_total = sum(row["cost_usd"] for row in custom_payload)
    assert custom_total != default_total


def test_report_date_filtering(capsys: pytest.CaptureFixture[str]) -> None:
    main(
        [
            "report",
            "--input",
            f"openai={OPENAI_EXPORT}",
            "--format",
            "json",
            "--group-by",
            "day",
            "--start-date",
            "2026-06-03",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    days = {row["day"] for row in payload}
    assert all(day >= "2026-06-03" for day in days)


def test_report_invalid_input_spec_returns_error(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["report", "--input", "not-a-valid-spec"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "error:" in err


def test_report_missing_file_returns_error(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["report", "--input", "openai=/no/such/file.json"])
    assert rc == 1


def test_report_bad_group_by_returns_error() -> None:
    rc = main(["report", "--input", f"openai={OPENAI_EXPORT}", "--group-by", "nonsense"])
    assert rc == 1


def test_drift_detects_regression(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "drift",
            "--input",
            f"anthropic={DRIFT_EXPORT}",
            "--baseline-start",
            "2026-06-01",
            "--baseline-end",
            "2026-06-06",
            "--current-start",
            "2026-06-08",
            "--current-end",
            "2026-06-13",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    regressions = [r for r in payload if r["is_regression"]]
    assert len(regressions) >= 1
    assert rc == 3


def test_drift_stable_group_not_flagged(capsys: pytest.CaptureFixture[str]) -> None:
    main(
        [
            "drift",
            "--input",
            f"anthropic={DRIFT_EXPORT}",
            "--baseline-start",
            "2026-06-01",
            "--baseline-end",
            "2026-06-06",
            "--current-start",
            "2026-06-08",
            "--current-end",
            "2026-06-13",
            "--format",
            "json",
            "--group-by",
            "model",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    by_model = {row["group_key"][0]: row for row in payload}
    assert by_model["claude-3-5-haiku-20241022"]["is_regression"] is False
    assert by_model["claude-3-5-sonnet-20241022"]["is_regression"] is True


def test_drift_table_format(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "drift",
            "--input",
            f"anthropic={DRIFT_EXPORT}",
            "--baseline-start",
            "2026-06-01",
            "--baseline-end",
            "2026-06-06",
            "--current-start",
            "2026-06-08",
            "--current-end",
            "2026-06-13",
        ]
    )
    assert rc == 3
    out = capsys.readouterr().out
    assert "REGRESSION" in out


def test_drift_csv_format(capsys: pytest.CaptureFixture[str]) -> None:
    main(
        [
            "drift",
            "--input",
            f"anthropic={DRIFT_EXPORT}",
            "--baseline-start",
            "2026-06-01",
            "--baseline-end",
            "2026-06-06",
            "--current-start",
            "2026-06-08",
            "--current-end",
            "2026-06-13",
            "--format",
            "csv",
        ]
    )
    out = capsys.readouterr().out
    assert "is_regression" in out.splitlines()[0]


def test_drift_no_regression_exit_code_zero(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "drift",
            "--input",
            f"anthropic={DRIFT_EXPORT}",
            "--baseline-start",
            "2026-06-01",
            "--baseline-end",
            "2026-06-06",
            "--current-start",
            "2026-06-08",
            "--current-end",
            "2026-06-13",
            "--format",
            "json",
            "--group-by",
            "model",
            "--min-relative-increase",
            "0.99",
        ]
    )
    assert rc == 0


def test_drift_missing_required_dates_errors() -> None:
    with pytest.raises(SystemExit):
        main(["drift", "--input", f"anthropic={DRIFT_EXPORT}"])


def test_main_requires_a_command() -> None:
    with pytest.raises(SystemExit):
        main([])
