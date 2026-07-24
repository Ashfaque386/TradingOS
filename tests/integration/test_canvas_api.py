"""Live Canvas API integration test (Phase 4 Epic E4.3): src/api/routers/canvas.py's single
composite endpoint, against the real FastAPI app + real Postgres. No fixtures are seeded here --
this just asserts the endpoint responds with a well-formed (possibly all-null) snapshot against
whatever real state already exists, since the whole point of this endpoint is "whatever's
actually there right now," not a scripted scenario.
"""

from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_canvas_state_returns_a_well_formed_snapshot():
    response = client.get("/api/v1/canvas/state")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"latest_code", "latest_backtest", "latest_agent_activity"}

    if body["latest_code"] is not None:
        assert body["latest_code"]["python_code"]
    if body["latest_backtest"] is not None:
        assert "sharpe_ratio" in body["latest_backtest"]
    if body["latest_agent_activity"] is not None:
        assert body["latest_agent_activity"]["message"]
