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


def prompt_bool(label: str, default: bool, hint: str | None = None) -> bool:
    if hint:
        print(f"  {hint}")
    suffix = "Y/n" if default else "y/N"
    value = input(f"{label} ({suffix}): ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "true", "1"}


def prompt_choice(
    label: str,
    options: Iterable[str],
    default: str | None = None,
    descriptions: dict[str, str] | None = None,
) -> str:
    option_list = list(options)
    print(label)
    for index, option in enumerate(option_list, start=1):
        marker = " (default)" if option == default else ""
        print(f"  {index}. {option}{marker}")
        if descriptions and option in descriptions:
            print(f"     {descriptions[option]}")
    while True:
        value = input("Choose a number or press Enter: ").strip()
        if not value and default is not None:
            return default
        if value.isdigit():
            position = int(value) - 1
            if 0 <= position < len(option_list):
                return option_list[position]
        print("Invalid selection, please try again.")


def prompt_multi_choice(label: str, options: Iterable[str], default: Iterable[str] | None = None) -> list[str]:
    option_list = list(options)
    default_set = set(default or [])
    print(label)
    for index, option in enumerate(option_list, start=1):
        marker = " (default: on)" if option in default_set else ""
        print(f"  {index}. {option}{marker}")
    while True:
        value = input(
            "Enter comma-separated numbers, 'all', 'none', or press Enter to keep the defaults above: "
        ).strip().lower()
        if not value:
            return [option for option in option_list if option in default_set]
        if value == "all":
            return list(option_list)
        if value == "none":
            return []
        positions = [item.strip() for item in value.split(",") if item.strip()]
        if positions and all(item.isdigit() and 1 <= int(item) <= len(option_list) for item in positions):
            selected_indexes = sorted({int(item) - 1 for item in positions})
            return [option_list[i] for i in selected_indexes]
        print("Invalid selection. Use comma-separated numbers, 'all', 'none', or press Enter.")


def prompt_positive_int(label: str, default: int) -> int:
    while True:
        value = input(f"{label} [{default}]: ").strip()
        if not value:
            return default
        if value.isdigit() and int(value) > 0:
            return int(value)
        print("Please enter a positive whole number.")
