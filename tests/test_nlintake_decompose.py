from unittest.mock import MagicMock, patch

from nlintake.decompose import decompose_query
from nlintake.models import DetectedMention, DetectedMentions


@patch("nlintake.decompose.get_llm")
def test_decompose_query_returns_mentions(mock_get_llm):
    expected = DetectedMentions(
        mentions=[
            DetectedMention(mentioned_service="payment system", notes="not working"),
            DetectedMention(mentioned_service="secrets", notes="not present"),
        ]
    )
    structured_llm = MagicMock()
    structured_llm.invoke.return_value = expected
    llm = MagicMock()
    llm.with_structured_output.return_value = structured_llm
    mock_get_llm.return_value = llm

    result = decompose_query("my payment system isn't working, also secrets aren't present")

    llm.with_structured_output.assert_called_once_with(DetectedMentions)
    assert result == expected.mentions


@patch("nlintake.decompose.get_llm")
def test_decompose_query_empty_result_falls_back_to_raw_query(mock_get_llm):
    structured_llm = MagicMock()
    structured_llm.invoke.return_value = DetectedMentions(mentions=[])
    llm = MagicMock()
    llm.with_structured_output.return_value = structured_llm
    mock_get_llm.return_value = llm

    result = decompose_query("something vague")

    assert len(result) == 1
    assert result[0].mentioned_service == "something vague"
