"""REL-010 E10.3: sentiment scoring/parsing logic, mocked LLM + Qdrant write -- the real
end-to-end LLM call + real Qdrant round trip is covered separately in
tests/integration/test_news_memory.py."""

from datetime import UTC, datetime
from unittest.mock import patch

from src.agents.nodes.news_agent import NewsItem
from src.agents.nodes.sentiment_agent import score_and_store_sentiment


def _fake_llm_response(content: str):
    class _Choice:
        def __init__(self, content: str) -> None:
            self.message = type("Message", (), {"content": content})()

    class _Response:
        def __init__(self, content: str) -> None:
            self.choices = [_Choice(content)]

    return _Response(content)


def _item(title: str = "Nifty ends higher on IT sector rally") -> NewsItem:
    return NewsItem(
        title=title,
        summary="Indian benchmark indices closed higher led by IT stocks.",
        source="test-source",
        url="https://example.invalid/article",
        published_at=datetime.now(UTC),
        guid="test-guid-1",
    )


@patch("src.agents.nodes.sentiment_agent.ingest_news_sentiment")
@patch("src.agents.nodes.sentiment_agent.complete")
def test_score_and_store_sentiment_parses_and_persists_a_valid_response(mock_complete, mock_ingest):
    mock_complete.return_value = _fake_llm_response(
        '{"sentiment": "Bullish", "confidence": 0.8, "symbols_mentioned": ["INFY", "TCS"]}'
    )
    mock_ingest.return_value = "point-1"

    point_ids = score_and_store_sentiment([_item()])

    assert point_ids == ["point-1"]
    mock_ingest.assert_called_once()
    kwargs = mock_ingest.call_args.kwargs
    assert kwargs["sentiment"] == "Bullish"
    assert kwargs["confidence"] == 0.8
    assert kwargs["symbols_mentioned"] == ["INFY", "TCS"]


@patch("src.agents.nodes.sentiment_agent.ingest_news_sentiment")
@patch("src.agents.nodes.sentiment_agent.complete")
def test_score_and_store_sentiment_skips_an_item_on_an_invalid_sentiment_value(
    mock_complete, mock_ingest
):
    mock_complete.return_value = _fake_llm_response(
        '{"sentiment": "VeryBullish", "confidence": 0.9, "symbols_mentioned": []}'
    )

    point_ids = score_and_store_sentiment([_item()])

    assert point_ids == []
    mock_ingest.assert_not_called()


@patch("src.agents.nodes.sentiment_agent.ingest_news_sentiment")
@patch("src.agents.nodes.sentiment_agent.complete")
def test_score_and_store_sentiment_skips_an_item_on_malformed_json(mock_complete, mock_ingest):
    mock_complete.return_value = _fake_llm_response("not json at all")

    point_ids = score_and_store_sentiment([_item()])

    assert point_ids == []
    mock_ingest.assert_not_called()


@patch("src.agents.nodes.sentiment_agent.ingest_news_sentiment")
@patch("src.agents.nodes.sentiment_agent.complete")
def test_one_bad_item_does_not_sink_the_whole_batch(mock_complete, mock_ingest):
    mock_complete.side_effect = [
        _fake_llm_response("not json"),
        _fake_llm_response('{"sentiment": "Neutral", "confidence": 0.5, "symbols_mentioned": []}'),
    ]
    mock_ingest.return_value = "point-2"

    point_ids = score_and_store_sentiment([_item("bad"), _item("good")])

    assert point_ids == ["point-2"]
