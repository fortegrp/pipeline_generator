import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode, urlparse


STATIC_EXTENSIONS = (
    ".js", ".css", ".woff", ".woff2", ".ttf", ".otf",
    ".png", ".jpg", ".jpeg", ".svg", ".gif", ".ico",
    ".map", ".webp", ".bmp", ".mp4", ".webm", ".avi",
    ".mov", ".mp3", ".wav",
)

STATIC_SEGMENTS = {
    "js", "css", "fonts", "font", "images", "img",
    "static", "assets", "media",
    "woff", "woff2", "ttf", "otf", "png", "jpg",
    "jpeg", "svg", "gif", "ico", "map", "webp",
}

TRACKER_HOSTS = (
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "googlesyndication.com",
    "hotjar.com",
    "mixpanel.com",
    "segment.io",
    "segment.com",
    "sentry.io",
    "datadoghq.com",
    "datadoghq.eu",
    "browser-intake-datadoghq.com",
    "app-measurement.com",
    "amplitude.com",
    "nr-data.net",
    "js-agent.newrelic.com",
    "logrocket.io",
    "bugsnag.com",
    "rollbar.com",
)

FONT_HOSTS = (
    "fonts.googleapis.com",
    "fonts.gstatic.com",
)


@dataclass(frozen=True)
class NormalizedRequest:
    entry_index: int
    method: str
    url: str
    headers: List[Dict[str, Any]]
    body: Optional[str]
    path: str
    host: str
    last_segment: str
    safe_segment: str
    base_name: str
    file_name: str
    test_name: str


@dataclass(frozen=True)
class SkippedRequest:
    entry_index: int
    method: str
    url: str
    reason: str


@dataclass(frozen=True)
class ProcessedRequests:
    requests: List[NormalizedRequest]
    skipped: List[SkippedRequest]


def extract_last_segment(path: str) -> str:
    """
    Returns the last path segment after the last "/".
    """
    if not path:
        return "root"

    if path.endswith("/"):
        path = path[:-1]

    if not path:
        return "root"

    segment = path.split("/")[-1]
    return segment if segment else "root"


def slugify(text: str) -> str:
    """
    Make a filesystem-safe name.
    """
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    return text.strip("_") or "root"


def extract_body(post_data: Any) -> Optional[str]:
    """
    Returns the request body text for a HAR postData object.
    Falls back to url-encoding postData.params when text is absent, since
    some HAR captures store form-encoded bodies only as params.
    """
    if not isinstance(post_data, dict):
        return None

    text = post_data.get("text")
    if text is not None:
        return text

    params = post_data.get("params")
    if not isinstance(params, list):
        return None

    pairs = [
        (str(param.get("name", "")), str(param.get("value", "")))
        for param in params
        if isinstance(param, dict)
    ]
    return urlencode(pairs) if pairs else None


def process_har_entries(entries: Iterable[Any], project: str, product: str, config: Any = None) -> ProcessedRequests:
    """
    Filter, normalize, de-duplicate, and name HAR requests.
    """
    if config is None:
        from converter_config import default_config

        config = default_config()

    normalized: List[NormalizedRequest] = []
    skipped: List[SkippedRequest] = []
    seen: set[Tuple[str, str]] = set()
    base_name_counts: Dict[str, int] = {}

    for entry_index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            skipped.append(SkippedRequest(entry_index, "GET", "", "entry is not an object"))
            continue

        req = entry.get("request", {})
        if not isinstance(req, dict):
            skipped.append(SkippedRequest(entry_index, "GET", "", "request is not an object"))
            continue

        url = req.get("url") or ""
        method = (req.get("method") or "GET").upper()

        reason = skip_reason(req, method, url, config)
        if reason:
            skipped.append(SkippedRequest(entry_index, method, url, reason))
            continue

        key = (method, url)
        if key in seen:
            skipped.append(SkippedRequest(entry_index, method, url, "duplicate method and URL"))
            continue
        seen.add(key)

        parsed = urlparse(url)
        path = parsed.path or "/"
        host = (parsed.hostname or "").lower()
        last_segment = extract_last_segment(path).lower()
        safe_segment = slugify(last_segment or "root")
        base_name = f"{project}_{product}_{method}_{safe_segment}"

        base_count = base_name_counts.get(base_name, 0) + 1
        base_name_counts[base_name] = base_count
        unique_base_name = base_name if base_count == 1 else f"{base_name}_{base_count}"

        body = extract_body(req.get("postData"))
        headers = req.get("headers", [])
        if not isinstance(headers, list):
            headers = []

        normalized.append(
            NormalizedRequest(
                entry_index=entry_index,
                method=method,
                url=url,
                headers=headers,
                body=body,
                path=path,
                host=host,
                last_segment=last_segment,
                safe_segment=safe_segment,
                base_name=unique_base_name,
                file_name=f"{unique_base_name}.jmx",
                test_name=unique_base_name,
            )
        )

    return ProcessedRequests(requests=normalized, skipped=skipped)


def skip_reason(req: Dict[str, Any], method: str, url: str, config: Any) -> Optional[str]:
    if not url.lower().startswith(("http://", "https://")):
        return "URL is not HTTP or HTTPS"

    lower_url = url.lower()

    if any(keep in lower_url for keep in config.filters.keep_url_contains):
        return None

    if method in config.filters.skip_methods:
        return f"{method} request"

    if any(skip in lower_url for skip in config.filters.skip_url_contains):
        return "skipped URL substring"

    headers = req.get("headers", [])
    if isinstance(headers, list) and any("nrjs" in str(h.get("value", "")).lower() for h in headers if isinstance(h, dict)):
        return "New Relic header"

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    path_lower = path.lower()

    if "favicon.ico" in path_lower:
        return "favicon"

    if host in config.filters.skip_exact_hosts:
        return "skipped exact host"

    if any(skip_host in host for skip_host in config.filters.skip_host_contains):
        return "skipped host substring"

    if path_lower.endswith(tuple(config.filters.skip_extensions)):
        return "static file extension"

    last_segment = extract_last_segment(path).lower()
    if last_segment in config.filters.skip_final_segments:
        return "static path segment"

    return None
