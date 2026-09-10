import pytest

from pipeline_generator.wizard.flow import _prompt_automated_jobs_section, _prompt_catalog_section


def test_prompt_catalog_section_keep_as_is(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(["1"])  # "keep as-is" is option 1
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))

    existing = [{"key": "qa", "name": "QA", "identifier": "env-qa"}]
    result = _prompt_catalog_section("environment", existing)

    assert result is existing


def test_prompt_catalog_section_start_over(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(
        [
            "3",  # "start over"
            "staging",  # new key
            "Staging",  # display name
            "env-staging",  # identifier
            "",  # blank key ends collection
        ]
    )
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))

    existing = [{"key": "qa", "name": "QA", "identifier": "env-qa"}]
    result = _prompt_catalog_section("environment", existing)

    assert result == [{"key": "staging", "name": "Staging", "identifier": "env-staging"}]


def test_prompt_catalog_section_add_more(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(
        [
            "2",  # "add more"
            "staging",
            "Staging",
            "env-staging",
            "",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))

    existing = [{"key": "qa", "name": "QA", "identifier": "env-qa"}]
    result = _prompt_catalog_section("environment", existing)

    assert result == [
        {"key": "qa", "name": "QA", "identifier": "env-qa"},
        {"key": "staging", "name": "Staging", "identifier": "env-staging"},
    ]


def test_prompt_catalog_section_no_existing_declines_adding(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(["n"])  # "Add environments now?" -> no
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))

    result = _prompt_catalog_section("environment", [])

    assert result == []


def test_prompt_automated_jobs_section_keep_as_is(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(["1"])  # "keep as-is"
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))

    existing_job = {
        "name": "nightly",
        "enabled": True,
        "environment_ref": "qa",
        "scenario_ref": "checkout_smoke",
        "timeout_minutes": 240,
    }
    config = {
        "automated_jobs": [existing_job],
        "catalog": {"environments": [], "scenarios": []},
    }
    result = _prompt_automated_jobs_section(config)

    assert result == [existing_job]
