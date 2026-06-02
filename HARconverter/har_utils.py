import json
from os import PathLike
from typing import Any, List, Union


def load_har_entries(har_path: Union[str, PathLike[str]]) -> List[Any]:
    """
    Load HAR file and return list of entries in a normalized way.
    Supports:
      { "log": { "entries": [...] } }
      { "entries": [...] }
      [ { "request": ... }, ... ]
    """
    with open(har_path, "r", encoding="utf-8") as f:
        har = json.load(f)

    if isinstance(har, dict):
        if "log" in har and isinstance(har["log"], dict) and "entries" in har["log"]:
            entries = har["log"]["entries"]
        elif "entries" in har and isinstance(har["entries"], list):
            entries = har["entries"]
        else:
            entries = []
    elif isinstance(har, list):
        entries = har
    else:
        entries = []

    return entries
