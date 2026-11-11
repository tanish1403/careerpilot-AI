import pytest
from careerpilot.applications.classifier import classify_question

SENS = [
    ("Are you legally authorized to work in the United States?", "work_authorization"),
    ("Will you require visa sponsorship?", "work_authorization"),
    ("Gender", "demographic"), ("What is your race/ethnicity?", "demographic"),
    ("Veteran status", "demographic"), ("Are you at least 18 years of age?", "demographic"),
    ("Do you have a disability?", "disability"),
    ("Have you ever been convicted of a felony?", "legal"),
    ("Are you subject to a non-compete agreement?", "legal"),
    ("Do you consent to a background check?", "background_check"),
    ("Willing to take a drug test?", "background_check"),
    ("I agree to the privacy policy", "consent"),
    ("I consent to receive text messages", "consent"),
    ("Social Security Number", "identifier"),
]


@pytest.mark.parametrize("q,cat", SENS)
def test_sensitive(q, cat):
    c = classify_question(q)
    assert c.sensitive and c.category == cat and not c.answerable


@pytest.mark.parametrize("q,topic", [
    ("First Name *", "first_name"), ("Last Name", "last_name"), ("Full legal name", "full_name"),
    ("Email *", "email"), ("Phone (required)", "phone"), ("LinkedIn Profile", "linkedin"),
    ("Current company", "current_company"), ("Location (City)", "location"),
])
def test_profile_topics(q, topic):
    c = classify_question(q)
    assert not c.sensitive and c.topic == topic and c.answerable


@pytest.mark.parametrize("q", ["Why do you want to work here?", "Expected salary",
                               "Describe a hard bug you fixed", "Favourite colour", ""])
def test_unmatched_needs_user(q):
    c = classify_question(q)
    assert not c.sensitive and c.topic is None and c.category == "needs_user"


def test_legal_name_is_not_sensitive():
    assert not classify_question("Full legal name").sensitive
