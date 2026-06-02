from __future__ import annotations

from pathlib import Path

from pipeline_generator.config.loader import save_config
from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.azure_devops import render_azure_devops
from pipeline_generator.renderers.github_actions import render_github_actions
from pipeline_generator.renderers.readme import render_setup_readme


def generate_assets(config: dict, output_dir: Path) -> list[str]:
    package = build_generic_package(config)
    setup_dir = output_dir / package.setup_id
    setup_dir.mkdir(parents=True, exist_ok=True)

    save_config(setup_dir / "customer.yaml", config)
    outputs = [str(setup_dir / "customer.yaml")]

    if package.cicd_type == "github_actions":
        outputs.extend(render_github_actions(config, package, setup_dir))
    elif package.cicd_type == "azure_devops":
        outputs.extend(render_azure_devops(config, package, setup_dir))
    else:  # pragma: no cover
        raise ValueError(f"Unsupported renderer: {package.cicd_type}")

    readme_path = setup_dir / "README.md"
    readme_path.write_text(render_setup_readme(config, package), encoding="utf-8")
    outputs.append(str(readme_path))

    return outputs

