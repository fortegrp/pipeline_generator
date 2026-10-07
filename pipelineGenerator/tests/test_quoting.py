from pipeline_generator.renderers.quoting import blazemeter_timeout_flag


def test_blazemeter_timeout_flag_empty_for_other_tools() -> None:
    assert blazemeter_timeout_flag("jmeter", 30) == ""
    assert blazemeter_timeout_flag("loadrunner_professional", 30) == ""


def test_blazemeter_timeout_flag_default_separator() -> None:
    assert blazemeter_timeout_flag("blazemeter", 30) == " --timeout-minutes 25"


def test_blazemeter_timeout_flag_custom_separator() -> None:
    assert blazemeter_timeout_flag("blazemeter", 30, separator="\n          ") == "\n          --timeout-minutes 25"


def test_groovy_squote_escapes_newlines() -> None:
    # A raw newline inside a Groovy single-quoted string is a compile error.
    from pipeline_generator.renderers.quoting import groovy_squote

    assert groovy_squote("a\nb\rc") == "'a\\nb\\rc'"


def test_blazemeter_timeout_flag_leaves_margin_before_the_job_timeout() -> None:
    # The CI job would otherwise be killed at the same moment the script gives
    # up, so the script's own timeout handling (stop the test, write the
    # summary) would never run.
    assert blazemeter_timeout_flag("blazemeter", 120) == " --timeout-minutes 115"
    assert blazemeter_timeout_flag("blazemeter", 3) == " --timeout-minutes 1"
