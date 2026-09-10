from pipeline_generator.config.schema import base_config, required_field_values


def test_required_field_values_resolves_base_config_placeholders() -> None:
    resolved = dict(required_field_values(base_config()))

    assert resolved == {
        "setup.id": "TODO",
        "setup.target_repository": "TODO",
        "cicd.type": "TODO",
        "tool.type": "TODO",
        "tool.auth.type": "TODO",
    }


def test_required_field_values_resolves_filled_in_config() -> None:
    config = base_config()
    config["setup"]["id"] = "example-setup"
    config["setup"]["target_repository"] = "https://example.com/repo.git"
    config["cicd"]["type"] = "github_actions"
    config["tool"]["type"] = "jmeter"
    config["tool"]["auth"]["type"] = "none"

    resolved = dict(required_field_values(config))

    assert resolved["setup.id"] == "example-setup"
    assert resolved["tool.auth.type"] == "none"


def test_required_field_values_returns_none_for_malformed_section_instead_of_crashing() -> None:
    config = base_config()
    config["tool"] = None

    resolved = dict(required_field_values(config))

    assert resolved["tool.type"] is None
    assert resolved["tool.auth.type"] is None
