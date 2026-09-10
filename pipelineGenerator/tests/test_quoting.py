from pipeline_generator.renderers.quoting import blazemeter_timeout_flag


def test_blazemeter_timeout_flag_empty_for_other_tools() -> None:
    assert blazemeter_timeout_flag("jmeter", 30) == ""
    assert blazemeter_timeout_flag("loadrunner_professional", 30) == ""


def test_blazemeter_timeout_flag_default_separator() -> None:
    assert blazemeter_timeout_flag("blazemeter", 30) == " --timeout-minutes 30"


def test_blazemeter_timeout_flag_custom_separator() -> None:
    assert blazemeter_timeout_flag("blazemeter", 30, separator="\n          ") == "\n          --timeout-minutes 30"
