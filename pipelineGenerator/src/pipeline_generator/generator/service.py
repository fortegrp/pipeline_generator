from __future__ import annotations

import shutil
from pathlib import Path

from pipeline_generator.config.loader import save_config
from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.azure_devops import render_azure_devops
from pipeline_generator.renderers.github_actions import render_github_actions
from pipeline_generator.renderers.jenkins import render_jenkins
from pipeline_generator.renderers.readme import render_setup_readme
from pipeline_generator.renderers.scripts import render_tool_script
from pipeline_generator.text_utils import slugify


def generate_assets(config: dict, output_dir: Path) -> list[str]:
    package = build_generic_package(config)
    # setup.id comes straight from the config file, which this tool's own
    # customer_repo/central_repo model expects to be editable by less-trusted
    # collaborators -- slugify it so a value like "../../etc" or an absolute
    # path can't write outside output_dir.
    setup_dir = output_dir / slugify(package.setup_id)
    # Wipe and rebuild rather than writing on top of a prior generation --
    # otherwise a stale file from an earlier config (e.g. the previous
    # tool's scripts/run-<tool_type>.sh, or a since-removed automated job's
    # workflow file) would silently survive alongside the new output.
    if setup_dir.exists():
        shutil.rmtree(setup_dir)
    setup_dir.mkdir(parents=True, exist_ok=True)

    save_config(setup_dir / "customer.yaml", config)
    outputs = [str(setup_dir / "customer.yaml")]

    outputs.extend(render_tool_script(config, package, setup_dir))

    if package.cicd_type == "github_actions":
        outputs.extend(render_github_actions(config, package, setup_dir))
    elif package.cicd_type == "azure_devops":
        outputs.extend(render_azure_devops(config, package, setup_dir))
    elif package.cicd_type == "jenkins":
        outputs.extend(render_jenkins(config, package, setup_dir))
    else:  # pragma: no cover
        raise ValueError(f"Unsupported renderer: {package.cicd_type}")

    readme_path = setup_dir / "README.md"
    readme_path.write_text(render_setup_readme(config, package), encoding="utf-8")
    outputs.append(str(readme_path))

    return outputs
