TODO_VALUE = "TODO"


def is_placeholder(value: object) -> bool:
    return value is None or value == "" or value == TODO_VALUE

