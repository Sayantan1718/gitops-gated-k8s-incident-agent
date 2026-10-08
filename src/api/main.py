"""HTTP wrapper around the same LangGraph flow run_agent.py drives from the
terminal. The interrupt/resume split across two endpoints (/scan and
/decision) exists because HTTP requests can't block on a terminal prompt —
the graph still genuinely pauses at the same human-approval gate either way.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from langgraph.types import Command
from pydantic import BaseModel

from src.agent.classifier import diagnosis_to_dict
from src.agent.graph import build_graph
from src.api.settings import Settings, get_settings
from src.k8s.client import list_unhealthy_pods, load_agent_client

app = FastAPI(
    title="Incident Remediation Agent API",
    description="Read-only diagnostic API + gated remediation workflow. Never mutates the cluster directly.",
    version="0.1.0",
)

_k8s_loaded = False
_graph = None


def ensure_k8s_loaded(settings: Settings = Depends(get_settings)) -> None:
    """Loads the agent's read-only kubeconfig once per process. Deliberately
    lazy (not a startup event) so the server can still boot and serve
    /health even if the cluster is temporarily unreachable.
    """
    global _k8s_loaded
    if not _k8s_loaded:
        load_agent_client(settings.kubeconfig_path)
        _k8s_loaded = True


def get_graph(_: None = Depends(ensure_k8s_loaded)):
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def _thread_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


class DiagnosticsResponse(BaseModel):
    namespace: str
    unhealthy_pods: list[dict]


class ScanResponse(BaseModel):
    thread_id: Optional[str] = None
    status: str
    diagnosis: Optional[dict] = None
    proposal: Optional[dict] = None


class DecisionRequest(BaseModel):
    approved: bool


class DecisionResponse(BaseModel):
    status: str
    pr_url: Optional[str] = None
    outcome: Optional[str] = None


class WebhookPayload(BaseModel):
    namespace: str
    reason: Optional[str] = None


def _run_scan(namespace: str, graph, settings: Settings) -> ScanResponse:
    thread_id = str(uuid.uuid4())
    initial_state = {
        "namespace": namespace,
        "gemini_api_key": settings.gemini_api_key,
        "github_token": settings.git_token,
        "git_repo": settings.git_repo,
        "git_base_branch": settings.git_base_branch,
    }
    result = graph.invoke(initial_state, _thread_config(thread_id))

    if "__interrupt__" not in result:
        return ScanResponse(status=result.get("outcome", "No unhealthy pods found."))

    payload = result["__interrupt__"][0].value
    return ScanResponse(
        thread_id=thread_id,
        status="awaiting_approval",
        diagnosis=payload["diagnosis"],
        proposal=payload["proposal"],
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/diagnostics/{namespace}", response_model=DiagnosticsResponse)
def get_diagnostics(namespace: str, _: None = Depends(ensure_k8s_loaded)) -> DiagnosticsResponse:
    """Read-only scan — lists unhealthy pods and their classified failure.
    No Gemini call, no state change anywhere. Safe to poll repeatedly.
    """
    diagnoses = list_unhealthy_pods(namespace)
    return DiagnosticsResponse(
        namespace=namespace,
        unhealthy_pods=[diagnosis_to_dict(d) for d in diagnoses],
    )


@app.post("/incidents/{namespace}/scan", response_model=ScanResponse)
def scan_namespace(
    namespace: str,
    graph=Depends(get_graph),
    settings: Settings = Depends(get_settings),
) -> ScanResponse:
    """Diagnoses + proposes a fix, pausing at the human-approval gate. Does
    NOT open a PR — call POST /incidents/{thread_id}/decision to act on it.
    """
    try:
        return _run_scan(namespace, graph, settings)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/incidents/{thread_id}/decision", response_model=DecisionResponse)
def decide(thread_id: str, decision: DecisionRequest, graph=Depends(get_graph)) -> DecisionResponse:
    """Resumes a paused graph run with a human decision. thread_id must come
    from a prior /scan call's response — there is no other code path that
    reaches create_pr_node without going through here.
    """
    snapshot = graph.get_state(_thread_config(thread_id))
    if not snapshot.next:
        # InMemorySaver loses all state on process restart (documented
        # limitation — see README). Without this check, resuming an unknown
        # thread_id silently restarts the graph from an empty state and
        # crashes deep inside diagnose_node with a confusing raw KeyError.
        raise HTTPException(
            status_code=404,
            detail=(
                f"No pending approval found for thread_id '{thread_id}'. "
                "It may have already been decided, or the server restarted "
                "since the /scan call (InMemorySaver does not persist across restarts)."
            ),
        )

    try:
        result = graph.invoke(Command(resume=decision.approved), _thread_config(thread_id))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return DecisionResponse(
        status="approved" if decision.approved else "rejected",
        pr_url=result.get("pr_url"),
        outcome=result.get("outcome"),
    )


@app.post("/webhook/cluster-event", response_model=ScanResponse)
def cluster_event_webhook(
    payload: WebhookPayload,
    graph=Depends(get_graph),
    settings: Settings = Depends(get_settings),
) -> ScanResponse:
    """Stub receiver for an external alert source (Prometheus Alertmanager,
    a custom k8s event watcher, etc.) to trigger a scan. Not wired to any
    real alerting system in this project — that integration is intentionally
    out of scope; this proves the entrypoint's shape and behaves like /scan.
    """
    try:
        return _run_scan(payload.namespace, graph, settings)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc