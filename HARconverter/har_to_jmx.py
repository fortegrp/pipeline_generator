#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Tuple

from converter_config import load_config, merge_host_maps
from har_utils import load_har_entries
from host_mapping import load_host_map
from jmx_generator import generate_jmx_files
from naming import validate_vars


def _parse_var(value: str) -> Tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError(f"--var must be KEY=VALUE, got: {value!r}")
    key, _, val = value.partition("=")
    return key, val


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert HAR requests into individual JMeter fragment JMX files."
    )
    parser.add_argument("har_path", help="HAR file to convert.")
    parser.add_argument(
        "host_mapping",
        nargs="?",
        default="",
        help="Optional CSV file with host,variableName mappings.",
    )
    parser.add_argument(
        "--var",
        action="append",
        type=_parse_var,
        default=[],
        metavar="KEY=VALUE",
        help="Naming template variable, e.g. --var project=Abbot. Repeatable.",
    )
    parser.add_argument(
        "--out-dir",
        default=".",
        help="Directory receiving generated JMX files. Defaults to current directory.",
    )
    parser.add_argument("--config", default="", help="Optional JSON converter configuration file.")
    parser.add_argument("--verbose", action="store_true", help="Print skipped request details.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    har_path = Path(args.har_path)
    out_dir = Path(args.out_dir)

    if not har_path.is_file():
        print(f"File not found: {har_path}", file=sys.stderr)
        sys.exit(1)

    try:
        config = load_config(args.config)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Failed to load config file {args.config}: {exc}", file=sys.stderr)
        sys.exit(1)

    template_vars = dict(args.var)

    try:
        validate_vars(config.naming.template, template_vars, reserved={"method", "segment"})
    except ValueError as exc:
        print(f"Invalid --var arguments: {exc}", file=sys.stderr)
        sys.exit(1)

    csv_host_map = load_host_map(args.host_mapping)
    if csv_host_map:
        print(f"Loaded {len(csv_host_map)} host mapping entries from {args.host_mapping}")
    host_var_map = merge_host_maps(config.hosts, csv_host_map)

    try:
        entries = load_har_entries(har_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Failed to load HAR file {har_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    if not entries:
        print("No entries found in HAR.")
        sys.exit(0)

    print(f"Generating JMX files into: {out_dir.resolve()}")
    count = generate_jmx_files(
        entries,
        template_vars,
        host_var_map,
        out_dir,
        verbose=args.verbose,
        config=config,
    )

    print(f"\nDone! Generated {count} JMX file(s).")


if __name__ == "__main__":
    main()
