"""Spec 011: the ecommerce demo chart renders for every scenario, and its
runbooks parse with the existing chunker. No cluster needed; the chart tests
skip when `helm` isn't installed."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from agent.classification import REASON_TO_FAILURE_CLASS
from knowledge_base.chunking import parse_runbook

ROOT = Path(__file__).parent.parent
CHART = ROOT / "demo" / "ecommerce"
RUNBOOKS = sorted((ROOT / "knowledge_base" / "runbooks").glob("ecommerce-*.md"))

SCENARIOS = {
    "oomPayment": ("payment", "200M"),
    "badImageCatalog": ("catalog", "does-not-exist"),
    "missingSecretCart": ("cart", "cart-redis-auth-v2"),
    "unschedulableFrontend": ("frontend", '"64"'),
    "badProbeFrontend": ("frontend", "/healthz-missing"),
    "badDbPasswordOrders": ("orders-db", "wrong-password"),
    "pvcUnboundPostgres": ("postgres", "postgres-data-fast"),
}

needs_helm = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def _render(*sets: str) -> str:
    args = ["helm", "template", "t", str(CHART)]
    for s in sets:
        args += ["--set", s]
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def _docs(rendered: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(rendered) if d]


@needs_helm
def test_healthy_chart_renders_all_workloads():
    docs = _docs(_render())
    deployments = {d["metadata"]["name"] for d in docs if d["kind"] == "Deployment"}
    assert deployments == {"frontend", "catalog", "cart", "orders", "payment", "postgres", "redis"}


@needs_helm
def test_healthy_chart_has_no_failure_markers():
    rendered = _render()
    for _, marker in SCENARIOS.values():
        assert marker not in rendered


@needs_helm
@pytest.mark.parametrize("value", SCENARIOS)
def test_each_scenario_renders_and_injects_its_failure(value):
    _, marker = SCENARIOS[value]
    rendered = _render(f"failures.{value}=true")
    assert marker in rendered
    assert _docs(rendered)


@pytest.mark.parametrize("path", RUNBOOKS, ids=lambda p: p.stem)
def test_ecommerce_runbook_parses_with_known_failure_class(path):
    frontmatter, sections = parse_runbook(path)
    assert frontmatter["id"] == path.stem
    assert frontmatter["failure_class"] in set(REASON_TO_FAILURE_CLASS.values())
    assert {name for name, _ in sections} == {"Diagnosis", "Remediation"}


def test_one_runbook_per_scenario():
    assert len(RUNBOOKS) == len(SCENARIOS)
