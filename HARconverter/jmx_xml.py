import xml.etree.ElementTree as ET
from typing import Optional, Tuple


def sub(parent: ET.Element, tag: str, text: Optional[str] = None, **attrs: str) -> ET.Element:
    element = ET.SubElement(parent, tag, attrs)
    if text is not None:
        element.text = text
    return element


def string_prop(parent: ET.Element, name: str, value: str = "") -> ET.Element:
    return sub(parent, "stringProp", value, name=name)


def bool_prop(parent: ET.Element, name: str, value: bool) -> ET.Element:
    return sub(parent, "boolProp", "true" if value else "false", name=name)


def jmx_to_string(root: ET.Element) -> str:
    ET.indent(root, space="  ")
    xml = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml}\n'


def build_test_plan_scaffold(name: str) -> Tuple[ET.Element, ET.Element]:
    """
    Builds the jmeterTestPlan root through a disabled TestFragmentController,
    shared by fragment (jmx_generator) and scenario (build_scenario_jmx) output.
    Returns (root, fragment_tree); callers append their own children to
    fragment_tree before serializing root with jmx_to_string.
    """
    root = ET.Element("jmeterTestPlan", version="1.2", properties="5.0", jmeter="5.6.0")
    root_tree = sub(root, "hashTree")

    test_plan = sub(
        root_tree,
        "TestPlan",
        guiclass="TestPlanGui",
        testclass="TestPlan",
        testname=name,
        enabled="true",
    )
    string_prop(test_plan, "TestPlan.comments")
    bool_prop(test_plan, "TestPlan.functional_mode", False)
    bool_prop(test_plan, "TestPlan.serialize_threadgroups", False)
    user_vars = sub(
        test_plan,
        "elementProp",
        name="TestPlan.user_defined_variables",
        elementType="Arguments",
        guiclass="ArgumentsPanel",
        testclass="Arguments",
        enabled="true",
    )
    sub(user_vars, "collectionProp", name="Arguments.arguments")
    string_prop(test_plan, "TestPlan.user_define_classpath")

    plan_tree = sub(root_tree, "hashTree")
    sub(
        plan_tree,
        "TestFragmentController",
        guiclass="TestFragmentControllerGui",
        testclass="TestFragmentController",
        testname=name,
        enabled="false",
    )
    fragment_tree = sub(plan_tree, "hashTree")

    return root, fragment_tree
