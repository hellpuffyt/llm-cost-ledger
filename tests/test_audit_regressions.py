"""Regression tests added during the production-readiness audit.

Every expected dollar figure here was computed by hand from the fixture
files (tokens x USD-per-million / 1,000,000), not by running the tool.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from llm_cost_ledger.cli import main
from llm_cost_ledger.ingest import IngestError, parse_anthropic_export, parse_openai_export
from llm_cost_ledger.models import UsageRecord
from llm_cost_ledger.pricing import PricingError, PricingTable

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _report_json(capsys: pytest.CaptureFixture[str], group_by: str) -> list[dict[str, object]]:
    code = main(
        [
            "report",
            "--input",
            f"openai={EXAMPLES / 'openai_usage.json'}",
            "--input",
            f"anthropic={EXAMPLES / 'anthropic_usage.csv'}",
            "--mapping",
            str(EXAMPLES / "mapping.yaml"),
            "--group-by",
            group_by,
            "--format",
            "json",
        ]
    )
    assert code == 0
    rows: list[dict[str, object]] = json.loads(capsys.readouterr().out)
    return rows


def test_example_costs_match_hand_computation(capsys: pytest.CaptureFixture[str]) -> None:
    # gpt-4o:       896,000 in x 2.50 + 248,000 out x 10.00          = 2.24 + 2.48 = 4.72
    # sonnet:       601,000 x 3.00 + 169,000 x 15.00
    #               + 20,100 cache-write x 3.75 + 81,000 cache-read x 0.30
    #               = 1.803 + 2.535 + 0.075375 + 0.0243               = 4.437675
    # gpt-4o-mini:  2,463,000 x 0.15 + 355,000 x 0.60 = 0.36945 + 0.213 = 0.58245
    # haiku:        361,000 x 0.80 + 72,500 x 4.00 = 0.2888 + 0.29     = 0.5788
    rows = {str(r["model"]): r["cost_usd"] for r in _report_json(capsys, "model")}
    assert rows == {
        "gpt-4o": 4.72,
        "claude-3-5-sonnet-20241022": 4.437675,
        "gpt-4o-mini": 0.58245,
        "claude-3-5-haiku-20241022": 0.5788,
    }


def test_table_rounds_exact_halves_up(capsys: pytest.CaptureFixture[str]) -> None:
    # 0.58245 used to print as 0.5824: the float sum was 0.58244999...
    code = main(
        [
            "report",
            "--input",
            f"openai={EXAMPLES / 'openai_usage.json'}",
            "--input",
            f"anthropic={EXAMPLES / 'anthropic_usage.csv'}",
            "--group-by",
            "model",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "0.5825" in out
    assert "0.5824" not in out
    assert "TOTAL: 10.3189 USD across 1198 requests" in out  # 10.318925


@pytest.mark.parametrize(
    ("amount", "places", "expected"),
    [
        (0.58245, 4, "0.5825"),
        (4.4376750000000005, 4, "4.4377"),
        (0.00015, 4, "0.0002"),
        (2.5, 0, "3"),
    ],
)
def test_format_usd_half_up(amount: float, places: int, expected: str) -> None:
    from llm_cost_ledger.report import format_usd

    assert format_usd(amount, places) == expected


def test_explicit_zero_cache_rate_is_free_not_input_rate() -> None:
    # `rate or input_rate` treated 0.0 as missing and charged $3 per 1M.
    table = PricingTable.from_yaml_text(
        "models:\n  m:\n    input_per_million: 3\n    output_per_million: 15\n"
        "    cache_read_per_million: 0\n    cache_write_per_million: 0\n"
    )
    record = UsageRecord(
        record_date=date(2026, 6, 1),
        provider="anthropic",
        model="m",
        input_tokens=0,
        output_tokens=0,
        request_count=1,
        cache_read_tokens=1_000_000,
        cache_write_tokens=1_000_000,
    )
    assert table.cost_of(record) == 0.0


def test_missing_cache_rate_still_falls_back_to_input_rate() -> None:
    table = PricingTable.from_yaml_text(
        "models:\n  m:\n    input_per_million: 3\n    output_per_million: 15\n"
    )
    record = UsageRecord(date(2026, 6, 1), "anthropic", "m", 0, 0, 1, cache_read_tokens=1_000_000)
    assert table.cost_of(record) == 3.0


@pytest.mark.parametrize("bad", ["-1", ".nan", ".inf"])
def test_negative_or_non_finite_prices_are_rejected(bad: str) -> None:
    with pytest.raises(PricingError):
        PricingTable.from_yaml_text(
            f"models:\n  m:\n    input_per_million: {bad}\n    output_per_million: 1\n"
        )


def test_invalid_yaml_is_a_pricing_error() -> None:
    with pytest.raises(PricingError, match="not valid YAML"):
        PricingTable.from_yaml_text("models: [\n")


HEADER = "date,workspace_id,model,input_tokens,output_tokens,request_count\n"


@pytest.mark.parametrize("value", ["inf", "nan", "12.7", "-10", "abc"])
def test_bad_token_counts_are_ingest_errors(value: str) -> None:
    with pytest.raises(IngestError):
        parse_anthropic_export(HEADER + f"2026-06-01,w,gpt-4o,{value},10,1\n")


def test_whole_float_token_counts_are_accepted() -> None:
    [record] = parse_anthropic_export(HEADER + "2026-06-01,w,gpt-4o,12.0,10,1\n")
    assert record.input_tokens == 12


@pytest.mark.parametrize("payload", ['{"data": [', "[1, 2]"])
def test_malformed_json_is_an_ingest_error(payload: str) -> None:
    with pytest.raises(IngestError):
        parse_openai_export(payload)


def _write(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


@pytest.mark.parametrize(
    ("name", "text", "extra"),
    [
        ("unk.csv", HEADER + "2026-06-01,w,no-such-model,10,10,1\n", []),
        ("neg.csv", HEADER + "2026-06-01,w,gpt-4o,-10,10,1\n", []),
        ("inf.csv", HEADER + "2026-06-01,w,gpt-4o,inf,10,1\n", []),
        ("ok.csv", HEADER + "2026-06-01,w,gpt-4o,1,1,1\n", ["--pricing", "BAD_YAML"]),
        ("ok.csv", HEADER + "2026-06-01,w,gpt-4o,1,1,1\n", ["--mapping", "BAD_YAML"]),
    ],
    ids=["unknown-model", "negative", "infinite", "bad-pricing-yaml", "bad-mapping-yaml"],
)
def test_cli_reports_errors_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str, text: str, extra: list[str]
) -> None:
    path = _write(tmp_path, name, text)
    bad_yaml = _write(tmp_path, "bad.yaml", "models: [\n")
    args = ["report", "--input", f"anthropic={path}"]
    args += [bad_yaml if a == "BAD_YAML" else a for a in extra]
    assert main(args) == 1
    assert capsys.readouterr().err.startswith("error: ")


def test_non_utf8_input_is_a_cli_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "latin.csv"
    path.write_bytes(HEADER.encode() + b"2026-06-01,w\xff,gpt-4o,1,1,1\n")
    assert main(["report", "--input", f"anthropic={path}"]) == 1
    assert "not valid UTF-8" in capsys.readouterr().err


DRIFT = [
    "drift",
    "--input",
    f"anthropic={EXAMPLES / 'drift_usage.csv'}",
    "--baseline-start",
    "2026-06-01",
    "--baseline-end",
    "2026-06-06",
    "--current-start",
    "2026-06-08",
    "--current-end",
    "2026-06-13",
]


def test_drift_rejects_out_of_range_alpha(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*DRIFT, "--alpha", "2"]) == 1
    assert "alpha" in capsys.readouterr().err


def test_drift_rejects_overlapping_periods(capsys: pytest.CaptureFixture[str]) -> None:
    args = [*DRIFT]
    args[args.index("--current-start") + 1] = "2026-06-05"
    assert main(args) == 1
    assert "overlap" in capsys.readouterr().err


def test_drift_json_is_strict_json_when_a_group_is_new(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A group with no baseline has relative_change = inf, which json.dumps
    # wrote as the invalid token `Infinity`.
    lines = [HEADER.rstrip("\n")]
    lines += [f"2026-06-{d:02d},w,gpt-4o,1000,100,1" for d in (8, 9, 10)]
    path = _write(tmp_path, "new.csv", "\n".join(lines) + "\n")
    args = [*DRIFT, "--format", "json"]
    args[2] = f"anthropic={path}"
    main(args)
    out = capsys.readouterr().out
    payload = json.loads(out, parse_constant=lambda c: pytest.fail(f"non-JSON constant {c}"))
    assert payload[0]["relative_change"] is None


def test_drift_table_columns_are_aligned(capsys: pytest.CaptureFixture[str]) -> None:
    main([*DRIFT, "--group-by", "model"])
    lines = capsys.readouterr().out.splitlines()
    assert set(lines[1]) <= {"-", " "}
    starts = {line.index("0.0") for line in lines[2:4]}
    assert len(starts) == 1
