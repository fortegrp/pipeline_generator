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


def _example_config_path() -> Path:
    return Path(__file__).parent.parent / "examples" / "github-jmeter" / "customer.yaml"


def test_validate_successful_config_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["validate", "--config", str(_example_config_path())])

    assert code == 0
    output = capsys.readouterr()
    assert "Errors:" not in output.out


def test_generate_successful_config_creates_files_and_exits_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["generate", "--config", str(_example_config_path()), "--output-dir", str(tmp_path)])

    assert code == 0
    output = capsys.readouterr()
    combined = output.out + output.err
    assert "Traceback" not in combined
    generated_scripts = list(tmp_path.rglob("run-jmeter.sh"))
    assert len(generated_scripts) == 1
    assert list(tmp_path.rglob("README.md"))


def test_validate_config_with_validation_errors_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad_config = tmp_path / "invalid.yaml"
    bad_config.write_text(
        "version: 1\nincomplete: false\ncicd:\n  type: not_a_real_platform\n", encoding="utf-8"
    )

    code = main(["validate", "--config", str(bad_config)])

    assert code == 1
    output = capsys.readouterr()
    assert "Errors:" in output.out
    assert "Traceback" not in output.out + output.err


def test_wizard_resume_from_malformed_draft_prints_clean_message_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    draft = tmp_path / "corrupt-draft.yaml"
    draft.write_text("key: [unclosed", encoding="utf-8")

    code = main(["wizard", "--output", str(draft), "--resume"])

    assert code == 1
    output = capsys.readouterr()
    combined = output.out + output.err
    assert "Traceback" not in combined
    assert str(draft) in combined


def test_wizard_eof_during_prompt_prints_clean_message_and_exits_130(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise_eof(*args: object, **kwargs: object) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise_eof)
    output_path = tmp_path / "draft.yaml"

    code = main(["wizard", "--output", str(output_path)])

    assert code == 130
    output = capsys.readouterr()
    combined = output.out + output.err
    assert "Traceback" not in combined
    assert "cancelled" in combined
