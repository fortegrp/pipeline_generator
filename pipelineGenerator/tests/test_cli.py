from __future__ import annotations

from pathlib import Path

import pytest

from pipeline_generator.cli import build_parser, main


def test_top_level_help_has_description(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    output = capsys.readouterr().out
    assert "customer YAML config" in output


def test_wizard_help_has_description(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["wizard", "--help"])
    output = capsys.readouterr().out
    assert "Interactively" in output


def test_validate_help_has_description(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["validate", "--help"])
    output = capsys.readouterr().out
    assert "errors" in output
    assert "warnings" in output


def test_generate_help_has_description(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["generate", "--help"])
    output = capsys.readouterr().out
    assert "README" in output


def test_validate_and_generate_config_argument_has_help_text(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    for command in ("validate", "generate"):
        with pytest.raises(SystemExit):
            parser.parse_args([command, "--help"])
        output = capsys.readouterr().out
        assert "customer.yaml" in output


def test_generate_missing_config_prints_clean_message_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.yaml"

    code = main(["generate", "--config", str(missing), "--output-dir", str(tmp_path / "out")])

    assert code == 1
    output = capsys.readouterr()
    combined = output.out + output.err
    assert "Traceback" not in combined
    assert str(missing) in combined


def test_validate_missing_config_prints_clean_message_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.yaml"

    code = main(["validate", "--config", str(missing)])

    assert code == 1
    output = capsys.readouterr()
    combined = output.out + output.err
    assert "Traceback" not in combined
    assert str(missing) in combined


def test_validate_malformed_yaml_prints_clean_message_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("key: [unclosed", encoding="utf-8")

    code = main(["validate", "--config", str(bad)])

    assert code == 1
    output = capsys.readouterr()
    combined = output.out + output.err
    assert "Traceback" not in combined


def test_generate_malformed_yaml_prints_clean_message_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("key: [unclosed", encoding="utf-8")

    code = main(["generate", "--config", str(bad), "--output-dir", str(tmp_path / "out")])

    assert code == 1
    output = capsys.readouterr()
    combined = output.out + output.err
    assert "Traceback" not in combined
