from pipeline_generator.wizard.id_builder import build_setup_id


def test_build_setup_id_slugifies_inputs() -> None:
    setup_id = build_setup_id("github_actions", "loadrunner_professional", "github.com/Acme/Store Front")
    assert setup_id == "github-actions-loadrunner-professional-store-front"

