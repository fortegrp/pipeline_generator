from pipeline_generator.wizard.id_builder import build_setup_id


def test_build_setup_id_slugifies_inputs() -> None:
    setup_id = build_setup_id("github_actions", "loadrunner_professional", "github.com/Acme/Store Front")
    assert setup_id == "github-actions-loadrunner-professional-store-front"


def test_build_setup_id_strips_git_suffix() -> None:
    setup_id = build_setup_id("github_actions", "jmeter", "https://github.com/acme/storefront.git")
    assert setup_id == "github-actions-jmeter-storefront"

