#!/usr/bin/env python3
import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

from converter_config import load_config
from har_requests import process_har_entries
from har_utils import load_har_entries


def _sub(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    element = ET.SubElement(parent, tag, attrs)
    if text is not None:
        element.text = text
    return element


def _string_prop(parent: ET.Element, name: str, value: str = "") -> ET.Element:
    return _sub(parent, "stringProp", value, name=name)


def _bool_prop(parent: ET.Element, name: str, value: bool) -> ET.Element:
    return _sub(parent, "boolProp", "true" if value else "false", name=name)


def _jmx_to_string(root: ET.Element) -> str:
    ET.indent(root, space="  ")
    xml = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml}\n'


def build_scenario_jmx(plan_name: str, include_files: List[str]) -> str:
    """
    Build a JMX with a Test Plan, disabled Test Fragment, and Include Controllers.
    """
    root = ET.Element("jmeterTestPlan", version="1.2", properties="5.0", jmeter="5.6.0")
    root_tree = _sub(root, "hashTree")

    test_plan = _sub(
        root_tree,
        "TestPlan",
        guiclass="TestPlanGui",
        testclass="TestPlan",
        testname=plan_name,
        enabled="true",
    )
    _string_prop(test_plan, "TestPlan.comments")
    _bool_prop(test_plan, "TestPlan.functional_mode", False)
    _bool_prop(test_plan, "TestPlan.serialize_threadgroups", False)
    user_vars = _sub(
        test_plan,
        "elementProp",
        name="TestPlan.user_defined_variables",
        elementType="Arguments",
        guiclass="ArgumentsPanel",
        testclass="Arguments",
        enabled="true",
    )
    _sub(user_vars, "collectionProp", name="Arguments.arguments")
    _string_prop(test_plan, "TestPlan.user_define_classpath")

    plan_tree = _sub(root_tree, "hashTree")
    _sub(
        plan_tree,
        "TestFragmentController",
        guiclass="TestFragmentControllerGui",
        testclass="TestFragmentController",
        testname=plan_name,
        enabled="false",
    )
    fragment_tree = _sub(plan_tree, "hashTree")

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
