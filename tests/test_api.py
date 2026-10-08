from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app, get_settings, get_graph, ensure_k8s_loaded
from src.api.settings import Settings
from src.agent.classifier import PodDiagnosis, FailureClass


def _fake_settings() -> Settings:
    return Settings(
        gemini_api_key="fake",
        kubeconfig_path="unused.yaml",
        git_token="fake",
        git_repo="org/repo",
        git_base_branch="main",
    )


@pytest.fixture(autouse=True)
def override_deps():
    app.dependency_overrides[get_settings] = _fake_settings
    app.dependency_overrides[ensure_k8s_loaded] = lambda: None
    yield
    app.dependency_overrides.clear()


client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@patch("src.api.main.list_unhealthy_pods")
def test_diagnostics_returns_unhealthy_pods(mock_list):
    mock_list.return_value = [
        PodDiagnosis("oom-demo-abc", "failure-lab", "stress", FailureClass.OOM_KILLED, "OOMKilled", None, 5)
    ]

    resp = client.get("/diagnostics/failure-lab")

    assert resp.status_code == 200
    body = resp.json()
    assert body["namespace"] == "failure-lab"
    assert body["unhealthy_pods"][0]["failure_class"] == "oom_killed"
    assert body["unhealthy_pods"][0]["restart_count"] == 5


def test_scan_returns_awaiting_approval_when_interrupt_hit():
    fake_interrupt = MagicMock()
    fake_interrupt.value = {
        "diagnosis": {"pod_name": "oom-demo-abc", "failure_class": "oom_killed"},
        "proposal": {"root_cause": "memory limit too low", "confidence": "high"},
    }
    fake_graph = MagicMock()
    fake_graph.invoke.return_value = {"__interrupt__": [fake_interrupt]}
    app.dependency_overrides[get_graph] = lambda: fake_graph

    resp = client.post("/incidents/failure-lab/scan")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "awaiting_approval"
    assert body["thread_id"] is not None
    assert body["diagnosis"]["pod_name"] == "oom-demo-abc"


def test_scan_returns_status_message_when_no_unhealthy_pods():
    fake_graph = MagicMock()
    fake_graph.invoke.return_value = {"outcome": "No unhealthy pods found in 'failure-lab'."}
    app.dependency_overrides[get_graph] = lambda: fake_graph

    resp = client.post("/incidents/failure-lab/scan")

    assert resp.status_code == 200
    body = resp.json()
    assert body["thread_id"] is None
    assert "No unhealthy pods" in body["status"]


def test_decision_approve_returns_pr_url():
    fake_graph = MagicMock()
    fake_graph.get_state.return_value = MagicMock(next=("create_pr",))
    fake_graph.invoke.return_value = {
        "pr_url": "https://github.com/org/repo/pull/1",
        "outcome": "PR opened: https://github.com/org/repo/pull/1",
    }
    app.dependency_overrides[get_graph] = lambda: fake_graph

    resp = client.post("/incidents/some-thread-id/decision", json={"approved": True})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert body["pr_url"] == "https://github.com/org/repo/pull/1"

    # Confirm the resume signal actually carried the approval through.
    call_args = fake_graph.invoke.call_args
    assert call_args[0][0].resume is True


def test_decision_reject_opens_no_pr():
    fake_graph = MagicMock()
    fake_graph.get_state.return_value = MagicMock(next=("create_pr",))
    fake_graph.invoke.return_value = {
        "outcome": "Rejected by reviewer — no PR opened, no action taken anywhere."
    }
    app.dependency_overrides[get_graph] = lambda: fake_graph

    resp = client.post("/incidents/some-thread-id/decision", json={"approved": False})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rejected"
    assert body["pr_url"] is None


def test_decision_on_unknown_thread_returns_404_not_a_crash():
    # Regression test for a real bug: resuming a thread_id with no saved
    # checkpoint (e.g. server restarted between /scan and /decision) used to
    # silently restart the graph from empty state and crash deep inside
    # diagnose_node with a bare KeyError('namespace').
    fake_graph = MagicMock()
    fake_graph.get_state.return_value = MagicMock(next=())  # nothing pending
    app.dependency_overrides[get_graph] = lambda: fake_graph

    resp = client.post("/incidents/stale-or-unknown-id/decision", json={"approved": True})

    assert resp.status_code == 404
    assert "No pending approval found" in resp.json()["detail"]
    fake_graph.invoke.assert_not_called()


def test_scan_failure_returns_502_not_500():
    fake_graph = MagicMock()
    fake_graph.invoke.side_effect = RuntimeError("cluster unreachable")
    app.dependency_overrides[get_graph] = lambda: fake_graph

    resp = client.post("/incidents/failure-lab/scan")

    assert resp.status_code == 502
    assert "cluster unreachable" in resp.json()["detail"]


def test_webhook_triggers_same_flow_as_scan():
    fake_graph = MagicMock()
    fake_graph.invoke.return_value = {"outcome": "No unhealthy pods found in 'failure-lab'."}
    app.dependency_overrides[get_graph] = lambda: fake_graph

    resp = client.post("/webhook/cluster-event", json={"namespace": "failure-lab"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "No unhealthy pods found in 'failure-lab'."