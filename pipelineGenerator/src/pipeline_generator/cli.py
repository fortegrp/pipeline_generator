from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline_generator.config.loader import load_config
from pipeline_generator.config.validator import ValidationResult, validate_config
from pipeline_generator.generator.service import generate_assets
from pipeline_generator.wizard.flow import run_wizard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline-generator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    wizard_parser = subparsers.add_parser("wizard", help="Create or resume a setup YAML interactively.")
    wizard_parser.add_argument("--output", type=Path, required=True, help="Path to the YAML file to create or update.")
    wizard_parser.add_argument("--resume", action="store_true", help="Resume from an existing YAML draft if present.")

    validate_parser = subparsers.add_parser("validate", help="Validate a setup YAML file.")
    validate_parser.add_argument("--config", type=Path, required=True)
    validate_parser.add_argument("--strict", action="store_true", help="Treat warnings as errors.")

    generate_parser = subparsers.add_parser("generate", help="Generate CI/CD files and README from a setup YAML file.")
    generate_parser.add_argument("--config", type=Path, required=True)
    generate_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("generated"),
        help="Directory where generated setup packages are created.",
    )

    return parser


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


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

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
        print(f"\nSaved setup draft to {args.output}")
        print(json.dumps({"setup_id": config["setup"]["id"], "incomplete": config["incomplete"]}, indent=2))
        print(f"\nNext step: pipeline-generator generate --config {args.output} --output-dir generated")
        return 0

    if args.command == "validate":
        config = load_config(args.config)
        result = validate_config(config)
        print(result.to_console())
        if result.errors or (args.strict and result.warnings):
            return 1
        return 0

    if args.command == "generate":
        config = load_config(args.config)
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
