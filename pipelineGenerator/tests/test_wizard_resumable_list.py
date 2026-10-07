import pytest

from pipeline_generator.wizard.flow import (
    _prompt_automated_jobs,
    _prompt_automated_jobs_section,
    _prompt_environments_section,
)

_QA = {"key": "qa", "identifier": "env-qa", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]}


def _feed(monkeypatch: pytest.MonkeyPatch, responses: list[str]) -> list[str]:
    prompts: list[str] = []
    answers = iter(responses)

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", fake_input)
    return prompts


def test_prompt_environments_section_keep_as_is_keeps_nested_scenarios(monkeypatch: pytest.MonkeyPatch) -> None:
    _feed(monkeypatch, ["1"])  # "keep as-is"

    existing = [_QA]
    result = _prompt_environments_section(existing, "jmeter")

    assert result is existing


def test_prompt_environments_section_collects_each_environments_scenarios(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _feed(
        monkeypatch,
        [
            "y",  # add environments now?
            "qa", "env-qa",
            "staging", "env-stg",
            "",  # end environments
            "checkout_smoke", "SC-1",  # qa's scenarios
            "browse", "SC-2",
            "",
            "checkout_smoke", "SC-3",  # staging's scenarios
            "",
        ],
    )

    result = _prompt_environments_section([], "jmeter")

    assert result == [
        {
            "key": "qa",
            "identifier": "env-qa",
            "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}, {"key": "browse", "identifier": "SC-2"}],
        },
        {"key": "staging", "identifier": "env-stg", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-3"}]},
    ]


def test_prompt_environments_section_reasks_invalid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _feed(monkeypatch, ["y", "qa: east", "qa-east", "env-qa", "", "smoke test", "smoke", "SC-1", ""])

    result = _prompt_environments_section([], "jmeter")

    assert result == [{"key": "qa-east", "identifier": "env-qa", "scenarios": [{"key": "smoke", "identifier": "SC-1"}]}]


def test_prompt_environments_section_add_more(monkeypatch: pytest.MonkeyPatch) -> None:
    _feed(monkeypatch, ["2", "staging", "env-stg", "", "checkout_smoke", "SC-3", ""])

    result = _prompt_environments_section([_QA], "jmeter")

    assert [env["key"] for env in result] == ["qa", "staging"]
    assert result[1]["scenarios"] == [{"key": "checkout_smoke", "identifier": "SC-3"}]


def test_prompt_environments_section_no_existing_declines_adding(monkeypatch: pytest.MonkeyPatch) -> None:
    _feed(monkeypatch, ["n"])

    assert _prompt_environments_section([], "jmeter") == []


def test_prompt_environments_section_identifier_labels_are_tool_specific(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = _feed(monkeypatch, ["y", "qa", "", "checkout_smoke", "C:\\s.lrs", ""])

    _prompt_environments_section([], "loadrunner_professional")

    assert any("Path to the .lrs scenario file" in p for p in prompts)


def test_prompt_automated_jobs_offers_only_chosen_environments_scenarios(monkeypatch: pytest.MonkeyPatch) -> None:
    config = {
        "catalog": {
            "environments": [
                _QA,
                {"key": "staging", "identifier": "env-stg", "scenarios": [{"key": "browse", "identifier": "SC-9"}]},
            ]
        }
    }
    prompts = _feed(monkeypatch, ["nightly", "2", "", "", ""])  # env 2 = staging, default scenario, timeout

    jobs = _prompt_automated_jobs(config)

    assert jobs[0]["environment_ref"] == "staging"
    assert jobs[0]["scenario_ref"] == "browse"


def test_prompt_automated_jobs_section_keep_as_is(monkeypatch: pytest.MonkeyPatch) -> None:
    _feed(monkeypatch, ["1"])

    existing_job = {
        "name": "nightly",
        "enabled": True,
        "environment_ref": "qa",
        "scenario_ref": "checkout_smoke",
        "timeout_minutes": 240,
    }
    config = {"automated_jobs": [existing_job], "catalog": {"environments": [_QA]}}

    assert _prompt_automated_jobs_section(config) == [existing_job]


@pytest.mark.parametrize("tool_type", ["loadrunner_professional", "blazemeter"])
def test_environment_identifier_is_only_asked_for_jmeter(monkeypatch: pytest.MonkeyPatch, tool_type: str) -> None:
    # Only JMeter's script reads the environment identifier (-Jenvironment).
    prompts = _feed(monkeypatch, ["y", "qa", "", "checkout_smoke", "SC-1", ""])

    result = _prompt_environments_section([], tool_type)

    assert result == [{"key": "qa", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]}]
    assert not any("Environment identifier" in p or "environment identifier" in p for p in prompts)
