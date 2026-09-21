import pytest

from pipeline_generator.wizard.flow import _prompt_automated_jobs_section, _prompt_catalog_section


def test_prompt_catalog_section_keep_as_is(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(["1"])  # "keep as-is" is option 1
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))

    existing = [{"key": "qa", "identifier": "env-qa"}]
    result = _prompt_catalog_section("environment", existing, "jmeter")

    assert result is existing


def test_prompt_catalog_section_start_over(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(
        [
            "3",  # "start over"
            "staging",  # new key
            "env-staging",  # identifier
            "",  # blank key ends collection
        ]
    )
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))

    existing = [{"key": "qa", "identifier": "env-qa"}]
    result = _prompt_catalog_section("environment", existing, "jmeter")

    assert result == [{"key": "staging", "identifier": "env-staging"}]


def test_prompt_catalog_section_add_more(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(
        [
            "2",  # "add more"
            "staging",
            "env-staging",
            "",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))

    existing = [{"key": "qa", "identifier": "env-qa"}]
    result = _prompt_catalog_section("environment", existing, "jmeter")

    assert result == [
        {"key": "qa", "identifier": "env-qa"},
        {"key": "staging", "identifier": "env-staging"},
    ]


def test_prompt_catalog_section_no_existing_declines_adding(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(["n"])  # "Add environments now?" -> no
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))

    result = _prompt_catalog_section("environment", [], "jmeter")

    assert result == []


def test_prompt_catalog_section_identifier_label_is_tool_specific(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []
    responses = iter(
        [
            "y",  # "Add environments now?"
            "qa",  # environment key
            "env-qa",  # identifier
            "",  # blank key ends collection
        ]
    )

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr("builtins.input", fake_input)

    _prompt_catalog_section("environment", [], "loadrunner_professional")

    assert any("not used by the generated script for LoadRunner" in p for p in prompts)


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
