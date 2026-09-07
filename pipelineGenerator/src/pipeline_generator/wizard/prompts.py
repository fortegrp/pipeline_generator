from __future__ import annotations

from typing import Iterable


def prompt_text(label: str, default: str | None = None, allow_blank: bool = True) -> str:
    suffix = f" [{default}]" if default not in (None, "") else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if not value and default is not None:
            return default
        if not value and not allow_blank:
            continue
        return value


def prompt_bool(label: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    value = input(f"{label} ({suffix}): ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "true", "1"}


def prompt_choice(label: str, options: Iterable[str], default: str | None = None) -> str:
    option_list = list(options)
    print(label)
    for index, option in enumerate(option_list, start=1):
        marker = " (default)" if option == default else ""
        print(f"  {index}. {option}{marker}")
    while True:
        value = input("Choose a number or press Enter: ").strip()
        if not value and default is not None:
            return default
        if value.isdigit():
            position = int(value) - 1
            if 0 <= position < len(option_list):
                return option_list[position]
        print("Invalid selection, please try again.")


def prompt_positive_int(label: str, default: int) -> int:
    while True:
        value = input(f"{label} [{default}]: ").strip()
        if not value:
            return default
        if value.isdigit() and int(value) > 0:
            return int(value)
        print("Please enter a positive whole number.")

