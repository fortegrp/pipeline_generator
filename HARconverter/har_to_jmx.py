#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

from converter_config import load_config, merge_host_maps
from har_utils import load_har_entries
from host_mapping import load_host_map
from jmx_generator import generate_jmx_files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert HAR requests into individual JMeter fragment JMX files."
    )
    parser.add_argument("har_path", help="HAR file to convert.")
    parser.add_argument("project", help="Project name used in generated JMX filenames.")
    parser.add_argument("product", help="Product name used in generated JMX filenames.")
    parser.add_argument(
        "host_mapping",
        nargs="?",
        default="",
        help="Optional CSV file with host,variableName mappings.",
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
        args.project,
        args.product,
        host_var_map,
        out_dir,
        verbose=args.verbose,
        config=config,
    )

    print(f"\nDone! Generated {count} JMX file(s).")


if __name__ == "__main__":
    main()
