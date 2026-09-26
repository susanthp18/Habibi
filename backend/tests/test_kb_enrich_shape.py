"""A request for information is a KB question even without a question word."""

from voice.kb_enrich import looks_like_kb_question


def test_asking_to_know_about_something_is_a_question():
    # VS-58097BA530: skipped as not_a_question, so the caller got no passages.
    assert looks_like_kb_question("I would like to know about. Car Protect 360.")
    assert looks_like_kb_question("Leave that, I want to know about insurance products")


def test_a_backchannel_is_still_not_a_question():
    assert not looks_like_kb_question("OK. Arrange a call back for it.")
    assert not looks_like_kb_question("Yes, from here.")
