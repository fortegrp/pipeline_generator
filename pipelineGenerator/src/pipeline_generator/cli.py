from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from pipeline_generator.config.loader import load_config
from pipeline_generator.config.validator import ValidationResult, validate_config
from pipeline_generator.generator.service import generate_assets
from pipeline_generator.wizard.flow import run_wizard

CONFIG_HELP = "Path to the customer.yaml setup file."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline-generator",
        description=(
            "Generate CI/CD pipeline files and a runnable performance-test script from a "
            "customer YAML config."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    wizard_parser = subparsers.add_parser(
        "wizard",
        help="Create or resume a setup YAML interactively.",
        description="Interactively build or resume a customer.yaml setup draft.",
    )
    wizard_parser.add_argument("--output", type=Path, required=True, help="Path to the YAML file to create or update.")
    wizard_parser.add_argument("--resume", action="store_true", help="Resume from an existing YAML draft if present.")

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate a setup YAML file.",
        description="Validate a customer.yaml setup file and report its errors and warnings.",
    )
    validate_parser.add_argument("--config", type=Path, required=True, help=CONFIG_HELP)
    validate_parser.add_argument("--strict", action="store_true", help="Treat warnings as errors.")

    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate CI/CD files and README from a setup YAML file.",
        description=(
            "Generate CI/CD pipeline files, a run script, and a README from a validated "
            "customer.yaml setup."
        ),
    )
    generate_parser.add_argument("--config", type=Path, required=True, help=CONFIG_HELP)
    generate_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("generated"),
        help="Directory where generated setup packages are created.",
    )

    return parser


def _load_config_or_none(config_path: Path) -> dict | None:
    """Load a config file, printing a clean message and returning None on expected failures.

    load_config() can raise OSError (missing file, permission issues, etc.) or a YAML parse
    error for malformed input -- both are user-input problems, not bugs, so they get a
    one-line message instead of a traceback.
    """
    try:
        return load_config(config_path)
    except OSError as exc:
        print(f"Could not read {config_path}: {exc.strerror or exc}")
        return None
    except yaml.YAMLError as exc:
        print(f"Could not parse {config_path} as YAML: {exc}")
        return None


def _blocks_action(result: ValidationResult, config: dict, action: str) -> bool:
    print(result.to_console())
    if result.errors:
        return True
    if result.warnings and not config.get("incomplete", False):
        print(
            f"This setup is marked complete (incomplete: false) but has warnings above. "
            f"Fix them, or set incomplete: true in the config to {action} as a draft anyway."
        )
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "wizard":
        if args.output.exists() and not args.resume:
            print(
                f"{args.output} already exists. Pass --resume to continue editing it, "
                "or choose a different --output path to start a new setup."
            )
            return 1
        try:
            config = run_wizard(args.output, resume=args.resume)
        except (EOFError, KeyboardInterrupt):
            if args.output.exists():
                print(f"\nWizard cancelled. Progress up to the last completed step was saved to {args.output}.")
            else:
                print("\nWizard cancelled before any progress was saved.")
            return 130
        except (OSError, yaml.YAMLError) as exc:
            print(f"Could not resume from {args.output}: {exc}")
            return 1
        print(f"\nSaved setup draft to {args.output}")
        print(json.dumps({"setup_id": config["setup"]["id"], "incomplete": config["incomplete"]}, indent=2))
        print(f"\nNext step: pipeline-generator generate --config {args.output} --output-dir generated")
        return 0

    if args.command == "validate":
        config = _load_config_or_none(args.config)
        if config is None:
            return 1
        result = validate_config(config)
        print(result.to_console())
        if result.errors or (args.strict and result.warnings):
            return 1
        return 0

    if args.command == "generate":
        config = _load_config_or_none(args.config)
        if config is None:
            return 1
        result = validate_config(config)
        if _blocks_action(result, config, "generate"):
            return 1
        outputs = generate_assets(config, args.output_dir)
        for output in outputs:
            print(output)
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
