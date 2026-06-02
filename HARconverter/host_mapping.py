import csv
import os
from typing import Dict


def load_host_map(path: str) -> Dict[str, str]:
    """
    Load host → variableName mapping from CSV (host,variable).
    Host is matched case-insensitively.
    Lines starting with '#' or blank are ignored.
    """
    mapping: Dict[str, str] = {}
    if not path:
        return mapping
    if not os.path.isfile(path):
        print(f"WARNING: host mapping file not found: {path}")
        return mapping

    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            first = row[0].strip()
            if not first or first.startswith("#"):
                continue
            if len(row) < 2:
                continue
            host = first.lower()
            var = row[1].strip()
            if host and var:
                mapping[host] = var
    return mapping