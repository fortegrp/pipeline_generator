import re

from pipeline_generator.wizard.id_builder import build_setup_id, generate_unique_setup_id


def test_build_setup_id_slugifies_inputs() -> None:
    setup_id = build_setup_id("github_actions", "loadrunner_professional")
    assert setup_id == "github-actions-loadrunner-professional"


def test_build_setup_id_combines_cicd_and_tool() -> None:
    setup_id = build_setup_id("github_actions", "jmeter")
    assert setup_id == "github-actions-jmeter"


def test_generate_unique_setup_id_appends_random_suffix() -> None:
    setup_id = generate_unique_setup_id("github_actions", "jmeter")
    assert re.fullmatch(r"github-actions-jmeter-[0-9a-f]{6}", setup_id)


def test_generate_unique_setup_id_is_not_deterministic() -> None:
    first = generate_unique_setup_id("github_actions", "jmeter")
    second = generate_unique_setup_id("github_actions", "jmeter")
    assert first != second

