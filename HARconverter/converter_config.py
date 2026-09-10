import json
from dataclasses import dataclass, field
from os import PathLike
from typing import Any, Dict, List, Optional, Union

from har_requests import FONT_HOSTS, STATIC_EXTENSIONS, STATIC_SEGMENTS, TRACKER_HOSTS


@dataclass(frozen=True)
class HeaderMaskRule:
    name: str
    replacement: str
    prefix: str = ""


@dataclass(frozen=True)
class NamingConfig:
    template: str = "{project}_{product}_{method}_{segment}"
    scenario_template: str = "{project}_{product}_{scenario_name}"


@dataclass(frozen=True)
class FilterConfig:
    skip_methods: List[str] = field(default_factory=list)
    skip_host_contains: List[str] = field(default_factory=list)
    skip_exact_hosts: List[str] = field(default_factory=list)
    skip_extensions: List[str] = field(default_factory=list)
    skip_final_segments: List[str] = field(default_factory=list)
    skip_url_contains: List[str] = field(default_factory=list)
    keep_url_contains: List[str] = field(default_factory=list)
    skip_header_value_contains: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class JMeterConfig:
    cookie_manager: bool = False
    cache_manager: bool = False
    http_defaults: bool = False
    http_defaults_protocol: str = "${__P(protocol,https)}"
    http_defaults_domain: str = "${__P(hostName)}"
    http_defaults_port: str = ""
    version: str = "5.6.0"


@dataclass(frozen=True)
class ConverterConfig:
    filters: FilterConfig
    hosts: Dict[str, str]
    header_masks: List[HeaderMaskRule]
    jmeter: JMeterConfig
    naming: NamingConfig


def default_config() -> ConverterConfig:
    return ConverterConfig(
        filters=FilterConfig(
            skip_methods=["OPTIONS"],
            skip_host_contains=list(TRACKER_HOSTS),
            skip_exact_hosts=list(FONT_HOSTS),
            skip_extensions=list(STATIC_EXTENSIONS),
            skip_final_segments=sorted(STATIC_SEGMENTS),
            skip_url_contains=["nrjs", "nr-data.net"],
            skip_header_value_contains=["nrjs"],
            keep_url_contains=[],
        ),
        hosts={},
        header_masks=[
            HeaderMaskRule(
                name="Authorization",
                prefix="Bearer ",
                replacement="Bearer ${TOKEN}",
            )
        ],
        jmeter=JMeterConfig(),
        naming=NamingConfig(),
    )


def load_config(path: Optional[Union[str, PathLike[str]]]) -> ConverterConfig:
    config = default_config()
    if not path:
        return config

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, dict):
        raise ValueError("config root must be a JSON object")

    return merge_config(config, raw)


def merge_config(base: ConverterConfig, raw: Dict[str, Any]) -> ConverterConfig:
    return ConverterConfig(
        filters=_merge_filters(base.filters, _object(raw, "filters")),
        hosts=_merge_hosts(base.hosts, _object(raw, "hosts")),
        header_masks=_merge_header_masks(base.header_masks, _object(raw, "headers")),
        jmeter=_merge_jmeter(base.jmeter, _object(raw, "jmeter")),
        naming=_merge_naming(base.naming, _object(raw, "naming")),
    )


def merge_host_maps(config_hosts: Dict[str, str], csv_hosts: Dict[str, str]) -> Dict[str, str]:
    merged = {host.lower(): var for host, var in config_hosts.items()}
    merged.update({host.lower(): var for host, var in csv_hosts.items()})
    return merged


def _object(raw: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = raw.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a JSON object")
    return value


def _merge_filters(base: FilterConfig, raw: Dict[str, Any]) -> FilterConfig:
    return FilterConfig(
        skip_methods=_merged_list(base.skip_methods, raw.get("skip_methods"), upper=True),
        skip_host_contains=_merged_list(base.skip_host_contains, raw.get("skip_host_contains"), lower=True),
        skip_exact_hosts=_merged_list(base.skip_exact_hosts, raw.get("skip_exact_hosts"), lower=True),
        skip_extensions=_merged_list(base.skip_extensions, raw.get("skip_extensions"), lower=True),
        skip_final_segments=_merged_list(base.skip_final_segments, raw.get("skip_final_segments"), lower=True),
        skip_url_contains=_merged_list(base.skip_url_contains, raw.get("skip_url_contains"), lower=True),
        keep_url_contains=_merged_list(base.keep_url_contains, raw.get("keep_url_contains"), lower=True),
        skip_header_value_contains=_merged_list(
            base.skip_header_value_contains, raw.get("skip_header_value_contains"), lower=True
        ),
    )


def _merge_hosts(base: Dict[str, str], raw: Dict[str, Any]) -> Dict[str, str]:
    merged = {host.lower(): var for host, var in base.items()}
    for host, var in raw.items():
        if not isinstance(var, str):
            raise ValueError("hosts values must be strings")
        clean_host = str(host).strip().lower()
        clean_var = var.strip()
        if clean_host and clean_var:
            merged[clean_host] = clean_var
    return merged


def _merge_header_masks(base: List[HeaderMaskRule], raw: Dict[str, Any]) -> List[HeaderMaskRule]:
    rules = list(base)
    raw_masks = raw.get("mask", [])
    if raw_masks is None:
        return rules
    if not isinstance(raw_masks, list):
        raise ValueError("headers.mask must be a list")

    for item in raw_masks:
        if not isinstance(item, dict):
            raise ValueError("headers.mask entries must be JSON objects")
        name = item.get("name")
        replacement = item.get("replacement")
        prefix = item.get("prefix", "")
        if not isinstance(name, str) or not isinstance(replacement, str) or not isinstance(prefix, str):
            raise ValueError("headers.mask entries require string name and replacement fields")
        rules.append(HeaderMaskRule(name=name, prefix=prefix, replacement=replacement))

    return rules


def _merge_jmeter(base: JMeterConfig, raw: Dict[str, Any]) -> JMeterConfig:
    return JMeterConfig(
        cookie_manager=_bool(raw, "cookie_manager", base.cookie_manager),
        cache_manager=_bool(raw, "cache_manager", base.cache_manager),
        http_defaults=_bool(raw, "http_defaults", base.http_defaults),
        http_defaults_protocol=_string(raw, "http_defaults_protocol", base.http_defaults_protocol),
        http_defaults_domain=_string(raw, "http_defaults_domain", base.http_defaults_domain),
        http_defaults_port=_string(raw, "http_defaults_port", base.http_defaults_port),
        version=_string(raw, "version", base.version),
    )


def _merge_naming(base: NamingConfig, raw: Dict[str, Any]) -> NamingConfig:
    return NamingConfig(
        template=_string(raw, "template", base.template, section="naming"),
        scenario_template=_string(raw, "scenario_template", base.scenario_template, section="naming"),
    )


def _merged_list(base: List[str], raw: Any, lower: bool = False, upper: bool = False) -> List[str]:
    if raw is None:
        values = list(base)
    else:
        if not isinstance(raw, list):
            raise ValueError("filter config values must be lists")
        values = list(base) + [str(item) for item in raw]

    normalized = []
    seen = set()
    for value in values:
        text = str(value).strip()
        if lower:
            text = text.lower()
        if upper:
            text = text.upper()
        if text and text not in seen:
            normalized.append(text)
            seen.add(text)
    return normalized


def _bool(raw: Dict[str, Any], key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"jmeter.{key} must be a boolean")
    return value


def _string(raw: Dict[str, Any], key: str, default: str, section: str = "jmeter") -> str:
    value = raw.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{section}.{key} must be a string")
    return value
