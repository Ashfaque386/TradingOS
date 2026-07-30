"""REL-009 E9.6 (TEST-014 Performance Tests, NFR-01/NFR-02-adjacent). A real Locust load test
against the real running `app` service -- not asserted as a blocking CI gate (load numbers are
inherently host-performance-dependent on this shared dev machine, same honest-measurement
reasoning as REL-008's ONNX inference latency test). Run manually:

    docker compose exec app locust -f tests/perf/locustfile.py --headless -u 50 -r 10 -t 60s \
        --host http://localhost:8000 --csv tests/perf/results

Reports real p50/p95/p99 request latency and real throughput for the 3 read endpoints a
dashboard session actually calls on load; there is no synthetic/mocked backend here.
"""

from locust import HttpUser, between, task

from src.core.db import get_session
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR, hash_password
from src.models.user import User

LOAD_TEST_EMAIL = "locust-load-test@example.invalid"
LOAD_TEST_PASSWORD = "locust-load-test-password-123"


def ensure_load_test_user() -> None:
    """Idempotent: creates the real user this load test authenticates as, if it doesn't already
    exist. Called once, by hand, before a real run -- not part of TradingOSUser itself, since
    every simulated user hitting this concurrently would race on the same INSERT."""
    with get_session() as session:
        from sqlalchemy import select

        existing = session.scalars(select(User).where(User.email == LOAD_TEST_EMAIL)).first()
        if existing is not None:
            return
        session.add(
            User(
                email=LOAD_TEST_EMAIL,
                hashed_password=hash_password(LOAD_TEST_PASSWORD),
                role=ROLE_SYSTEM_ADMINISTRATOR,
            )
        )
        session.commit()


class TradingOSUser(HttpUser):
    wait_time = between(1, 3)
    token: str | None = None

    def on_start(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": LOAD_TEST_EMAIL, "password": LOAD_TEST_PASSWORD},
        )
        response.raise_for_status()
        body = response.json()
        # MFA is currently disabled project-wide (REL-007) -- a real, immediately-usable token.
        self.token = body["access_token"]

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    @task(3)
    def list_agent_runs(self) -> None:
        self.client.get("/api/v1/agents/runs", headers=self._auth_headers(), name="/agents/runs")

    @task(2)
    def portfolio_risk_metrics(self) -> None:
        self.client.get(
            "/api/v1/portfolio/risk-metrics",
            headers=self._auth_headers(),
            name="/portfolio/risk-metrics",
        )

    @task(2)
    def list_strategies(self) -> None:
        self.client.get("/api/v1/strategies", headers=self._auth_headers(), name="/strategies")


if __name__ == "__main__":
    ensure_load_test_user()
    print(f"Real load-test user ready: {LOAD_TEST_EMAIL}")
    print(
        "Run the actual load test with: docker compose exec app locust -f "
        "tests/perf/locustfile.py --headless -u 50 -r 10 -t 60s --host http://localhost:8000"
    )
