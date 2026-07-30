"""REL-009 E9.7: proves k8s/tradingos/ is a real, valid Helm chart via helm's own tooling.

Not collected by the main `pytest` run configured elsewhere in this repo (see
`.github/workflows/ci.yml`'s separate `helm-lint` job, which shells out to the same two
`helm` subcommands directly) -- this module exists so the same check is also runnable and
readable as an ordinary pytest test, e.g. `pytest tests/ci/ -v`. Needs Docker (the
`alpine/helm` image) and is skipped if the Docker CLI isn't reachable, matching this repo's
existing pattern for host-environment-dependent tests (e.g. the live-broker/live-LangSmith
integration tests).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

CHART_DIR = Path(__file__).resolve().parents[2] / "k8s" / "tradingos"
EXPECTED_IMAGE = "ghcr.io/ashfaque386/tradingos"

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI not available")


def _run_helm(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{CHART_DIR}:/chart",
            "alpine/helm:latest",
            *args,
            "/chart",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_helm_lint_passes() -> None:
    result = _run_helm("lint")
    assert result.returncode == 0, f"helm lint failed:\n{result.stdout}\n{result.stderr}"


def test_helm_template_renders_expected_image() -> None:
    result = _run_helm("template")
    assert result.returncode == 0, f"helm template failed:\n{result.stdout}\n{result.stderr}"
    assert (
        EXPECTED_IMAGE in result.stdout
    ), f"rendered manifests don't reference the real CD-published image {EXPECTED_IMAGE!r}"


def test_chart_yaml_is_valid() -> None:
    chart_yaml = (CHART_DIR / "Chart.yaml").read_text()
    assert "name: tradingos" in chart_yaml
    assert "apiVersion: v2" in chart_yaml


def test_values_yaml_matches_ci_pushed_image_repository() -> None:
    values_yaml = (CHART_DIR / "values.yaml").read_text()
    assert EXPECTED_IMAGE in values_yaml


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps({"chart_dir": str(CHART_DIR)}))
