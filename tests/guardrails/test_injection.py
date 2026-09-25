import pytest

from guardrails.injection import find_injection
from guardrails.normalize import normalize

from .samples import BENIGN_LOG_LINES, INJECTION, VALID_INCIDENTS


@pytest.mark.parametrize("text", INJECTION)
def test_injection_samples_are_matched_after_normalisation(text):
    assert find_injection(normalize(text)) is not None


@pytest.mark.parametrize("text", VALID_INCIDENTS + BENIGN_LOG_LINES)
def test_benign_text_is_not_matched(text):
    assert find_injection(normalize(text)) is None


def test_encoded_blob_flags_user_input_but_not_evidence():
    blob = "A" * 300
    assert find_injection(blob) == "encoded_blob"
    assert find_injection(blob, for_evidence=True) is None
