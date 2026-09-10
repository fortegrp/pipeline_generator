#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import List

from converter_config import load_config
from har_requests import process_har_entries
from har_utils import load_har_entries
from jmx_xml import build_test_plan_scaffold, jmx_to_string as _jmx_to_string, string_prop as _string_prop, sub as _sub


def build_scenario_jmx(plan_name: str, include_files: List[str]) -> str:
    """
    Build a JMX with a Test Plan, disabled Test Fragment, and Include Controllers.
    """
    root, fragment_tree = build_test_plan_scaffold(plan_name)

    for jmx_file in include_files:
        base = Path(jmx_file).stem
        include = _sub(
            fragment_tree,
            "IncludeController",
            guiclass="IncludeControllerGui",
            testclass="IncludeController",
            testname=f"IC_{base}",
            enabled="true",
        )
        _string_prop(include, "IncludeController.includepath", jmx_file)
        _sub(fragment_tree, "hashTree")

    return _jmx_to_string(root)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a scenario JMX that includes generated HAR request fragments."
    )
    parser.add_argument("har_path", help="HAR file used to determine scenario order.")
    parser.add_argument("project", help="Project name used in generated fragment names.")
    parser.add_argument("product", help="Product name used in generated fragment names.")
    parser.add_argument("scenario_name", help="Scenario name used in the output JMX filename.")
    parser.add_argument(
        "--out-dir",
        default=".",
        help="Directory containing fragments and receiving the scenario JMX. Defaults to current directory.",
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

    try:
        entries = load_har_entries(har_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Failed to load HAR file {har_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    if not entries:
        print("No entries found in HAR.")
        sys.exit(0)

    processed = process_har_entries(entries, args.project, args.product, config)

    if args.verbose:
        for skipped in processed.skipped:
            print(f"Skipped #{skipped.entry_index}: {skipped.method} {skipped.url} ({skipped.reason})")

    include_files: List[str] = []
    for request in processed.requests:
        jmx_path = out_dir / request.file_name
        if jmx_path.is_file():
            include_files.append(request.file_name)
        else:
            print(f"WARNING: JMX not found for {request.method} {request.url} -> expected {request.file_name}")

    if not include_files:
        print("No matching JMX files found for HAR entries.")
        sys.exit(0)

    print(f"Will include {len(include_files)} JMX fragments:")
    for include_file in include_files:
        print(f"  {include_file}")

    out_dir.mkdir(parents=True, exist_ok=True)
    plan_name = f"{args.project}_{args.product}_{args.scenario_name}"
    output_path = out_dir / f"{plan_name}.jmx"
    output_path.write_text(build_scenario_jmx(plan_name, include_files), encoding="utf-8")

    print(f"\nScenario JMX created: {output_path}")


if __name__ == "__main__":
    main()
