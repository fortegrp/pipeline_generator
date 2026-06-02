from __future__ import annotations

from typing import Iterable


def prompt_text(label: str, default: str | None = None, allow_blank: bool = True) -> str:
    suffix = f" [{default}]" if default not in (None, "") else ""
    value = input(f"{label}{suffix}: ").strip()
    if not value and default is not None:
        return default
    if not value and not allow_blank:
        return prompt_text(label, default=default, allow_blank=allow_blank)
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
    value = input("Choose a number or press Enter: ").strip()
    if not value and default is not None:
        return default
    if value.isdigit():
        position = int(value) - 1
        if 0 <= position < len(option_list):
            return option_list[position]
    print("Invalid selection, please try again.")
    return prompt_choice(label, option_list, default=default)

