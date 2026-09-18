from pipeline_generator.wizard.id_builder import build_setup_id


def test_build_setup_id_slugifies_inputs() -> None:
    setup_id = build_setup_id("github_actions", "loadrunner_professional")
    assert setup_id == "github-actions-loadrunner-professional"


def test_build_setup_id_combines_cicd_and_tool() -> None:
    setup_id = build_setup_id("github_actions", "jmeter")
    assert setup_id == "github-actions-jmeter"

