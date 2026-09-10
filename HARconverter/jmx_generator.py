import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import parse_qsl, urlparse

from converter_config import ConverterConfig, default_config
from har_requests import NormalizedRequest, extract_last_segment, process_har_entries, slugify
from jmx_xml import (
    bool_prop as _bool_prop,
    build_test_plan_scaffold,
    jmx_to_string as _jmx_to_string,
    string_prop as _string_prop,
    sub as _sub,
)


def _build_arguments(parent: ET.Element, body: Optional[str], query_params: List[Tuple[str, str]]) -> None:
    args = _sub(
        parent,
        "elementProp",
        name="HTTPsampler.Arguments",
        elementType="Arguments",
        guiclass="HTTPArgumentsPanel",
        testclass="Arguments",
        enabled="true",
    )
    collection = _sub(args, "collectionProp", name="Arguments.arguments")

    if body is not None:
        arg = _sub(collection, "elementProp", name="", elementType="HTTPArgument")
        _bool_prop(arg, "HTTPArgument.always_encode", False)
        _string_prop(arg, "Argument.value", body)
        _string_prop(arg, "Argument.metadata", "=")
        return

    for name, value in query_params:
        arg = _sub(collection, "elementProp", name=name, elementType="HTTPArgument")
        _bool_prop(arg, "HTTPArgument.always_encode", False)
        _string_prop(arg, "Argument.name", name)
        _string_prop(arg, "Argument.value", value)
        _string_prop(arg, "Argument.metadata", "=")
        _bool_prop(arg, "HTTPArgument.use_equals", True)


def _normalized_headers(headers: Iterable[dict], host_var_map: Dict[str, str], config: ConverterConfig) -> List[Tuple[str, str]]:
    normalized: List[Tuple[str, str]] = []
    for header in headers:
        if not isinstance(header, dict):
            continue

        name = str(header.get("name", ""))
        value = str(header.get("value", ""))

        if name.startswith(":"):
            continue

        for rule in config.header_masks:
            if name.lower() != rule.name.lower():
                continue
            if rule.prefix and not value.lower().startswith(rule.prefix.lower()):
                continue
            value = rule.replacement
            break

        if value and host_var_map:
            for host, var in host_var_map.items():
                if host.lower() in value.lower():
                    pattern = re.compile(re.escape(host), re.IGNORECASE)
                    value = pattern.sub(f"${{__P({var})}}", value)

        normalized.append((name, value))

    return normalized


def _add_http_defaults(parent_tree: ET.Element, config: ConverterConfig) -> None:
    defaults = _sub(
        parent_tree,
        "ConfigTestElement",
        guiclass="HttpDefaultsGui",
        testclass="ConfigTestElement",
        testname="HTTP Request Defaults",
        enabled="true",
    )
    _string_prop(defaults, "HTTPSampler.domain", config.jmeter.http_defaults_domain)
    _string_prop(defaults, "HTTPSampler.port", config.jmeter.http_defaults_port)
    _string_prop(defaults, "HTTPSampler.protocol", config.jmeter.http_defaults_protocol)
    _sub(parent_tree, "hashTree")


def _add_cookie_manager(parent_tree: ET.Element) -> None:
    manager = _sub(
        parent_tree,
        "CookieManager",
        guiclass="CookiePanel",
        testclass="CookieManager",
        testname="HTTP Cookie Manager",
        enabled="true",
    )
    _sub(manager, "collectionProp", name="CookieManager.cookies")
    _bool_prop(manager, "CookieManager.clearEachIteration", False)
    _bool_prop(manager, "CookieManager.controlledByThreadGroup", False)
    _sub(parent_tree, "hashTree")


def _add_cache_manager(parent_tree: ET.Element) -> None:
    manager = _sub(
        parent_tree,
        "CacheManager",
        guiclass="CacheManagerGui",
        testclass="CacheManager",
        testname="HTTP Cache Manager",
        enabled="true",
    )
    _bool_prop(manager, "clearEachIteration", False)
    _bool_prop(manager, "useExpires", True)
    _sub(parent_tree, "hashTree")


def build_jmx_xml(
    test_name: str,
    method: str,
    url: str,
    headers: List[dict],
    body: Optional[str],
    host_var_map: Dict[str, str],
    config: Optional[ConverterConfig] = None,
) -> str:
    if config is None:
        config = default_config()

    parsed = urlparse(url)
    path = parsed.path or "/"

    if body is None and parsed.query:
        query_params = parse_qsl(parsed.query, keep_blank_values=True)
        path_for_sampler = path
    else:
        query_params = []
        path_for_sampler = path + (f"?{parsed.query}" if parsed.query else "")

    root, fragment_tree = build_test_plan_scaffold(test_name, config.jmeter.version)

    if config.jmeter.http_defaults:
        _add_http_defaults(fragment_tree, config)
    if config.jmeter.cookie_manager:
        _add_cookie_manager(fragment_tree)
    if config.jmeter.cache_manager:
        _add_cache_manager(fragment_tree)

    sampler = _sub(
        fragment_tree,
        "HTTPSamplerProxy",
        guiclass="HttpTestSampleGui",
        testclass="HTTPSamplerProxy",
        testname=test_name,
        enabled="true",
    )
    _build_arguments(sampler, body, query_params)
    _string_prop(sampler, "HTTPSampler.domain")
    _string_prop(sampler, "HTTPSampler.port")
    _string_prop(sampler, "HTTPSampler.protocol")
    _string_prop(sampler, "HTTPSampler.path", path_for_sampler)
    _string_prop(sampler, "HTTPSampler.method", method)
    _bool_prop(sampler, "HTTPSampler.follow_redirects", False)
    _bool_prop(sampler, "HTTPSampler.auto_redirects", False)
    _bool_prop(sampler, "HTTPSampler.use_keepalive", True)
    _bool_prop(sampler, "HTTPSampler.postBodyRaw", body is not None)

    sampler_tree = _sub(fragment_tree, "hashTree")
    header_manager = _sub(
        sampler_tree,
        "HeaderManager",
        guiclass="HeaderPanel",
        testclass="HeaderManager",
        testname="HTTP Header Manager",
        enabled="true",
    )
    header_collection = _sub(header_manager, "collectionProp", name="HeaderManager.headers")
    for name, value in _normalized_headers(headers, host_var_map, config):
        header = _sub(header_collection, "elementProp", name="", elementType="Header")
        _string_prop(header, "Header.name", name)
        _string_prop(header, "Header.value", value)
    _sub(sampler_tree, "hashTree")

    return _jmx_to_string(root)


def build_request_jmx_xml(
    request: NormalizedRequest,
    host_var_map: Dict[str, str],
    config: Optional[ConverterConfig] = None,
) -> str:
    return build_jmx_xml(
        request.test_name,
        request.method,
        request.url,
        request.headers,
        request.body,
        host_var_map,
        config,
    )


def generate_jmx_files(
    entries: List[Any],
    project: str,
    product: str,
    host_var_map: Dict[str, str],
    out_dir: Union[str, Path],
    verbose: bool = False,
    config: Optional[ConverterConfig] = None,
) -> int:
    """
    Iterate HAR entries, filter them, build JMX XML, and write files.
    Returns number of generated files.
    """
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if config is None:
        config = default_config()

    processed = process_har_entries(entries, project, product, config)

    if verbose:
        for skipped in processed.skipped:
            print(f"Skipped #{skipped.entry_index}: {skipped.method} {skipped.url} ({skipped.reason})")

    for request in processed.requests:
        xml = build_request_jmx_xml(request, host_var_map, config)
        out_path = output_dir / request.file_name
        out_path.write_text(xml, encoding="utf-8")
        print(f"Created {request.file_name}")

    return len(processed.requests)
