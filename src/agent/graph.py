"""The actual safety mechanism this whole project exists to demonstrate:
the graph pauses at human_approval_node via interrupt() and CANNOT proceed
to create_pr_node without an external Command(resume=...) call. There is no
code path from diagnosis to a PR that skips this pause.
"""
from __future__ import annotations

from typing import TypedDict, Optional

try:
    from langgraph.checkpoint.memory import InMemorySaver as _Saver
except ImportError:
    from langgraph.checkpoint.memory import MemorySaver as _Saver  # older langgraph versions

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command

from kubernetes import client as k8s_client
from src.agent.classifier import PodDiagnosis, diagnosis_to_dict, diagnosis_from_dict
from src.agent.models import FixProposal
from src.agent.gemini_client import propose_fix
from src.k8s.client import (
    list_unhealthy_pods,
    get_previous_pod_logs,
    get_pod_logs,
    get_owning_deployment,
    get_revision_diff,
    summarize_revision_diff,
)
from src.gitops.github_client import open_remediation_pr


class AgentState(TypedDict, total=False):
    namespace: str
    gemini_api_key: str
    github_token: str
    git_repo: str
    git_base_branch: str

    diagnosis: Optional[dict]
    logs: Optional[str]
    revision_diff: Optional[dict]
    deployment_name: Optional[str]
    manifest_path: Optional[str]

    proposal: Optional[dict]
    approved: Optional[bool]
    pr_url: Optional[str]
    outcome: Optional[str]  # human-readable final status, for the CLI to print


def diagnose_node(state: AgentState) -> dict:
    diagnoses = list_unhealthy_pods(state["namespace"])
    if not diagnoses:
        return {"outcome": f"No unhealthy pods found in '{state['namespace']}'."}

    diag = diagnoses[0]  # one incident per run — batching is a future extension, not built here
    logs = get_previous_pod_logs(state["namespace"], diag.pod_name, diag.container_name)
    if logs is None:
        logs = get_pod_logs(state["namespace"], diag.pod_name, diag.container_name)

    v1 = k8s_client.CoreV1Api()
    pod = v1.read_namespaced_pod(name=diag.pod_name, namespace=state["namespace"])
    deployment = get_owning_deployment(state["namespace"], pod)

    revision_diff = None
    deployment_name = None
    if deployment is not None:
        deployment_name = deployment.metadata.name
        raw_diff = get_revision_diff(state["namespace"], deployment_name)
        revision_diff = summarize_revision_diff(raw_diff) if raw_diff else None

    return {
        "diagnosis": diagnosis_to_dict(diag),
        "logs": logs,
        "revision_diff": revision_diff,
        "deployment_name": deployment_name,
        # Naming convention: the GitOps repo must have manifests/<deployment-name>.yaml.
        # See README for how the seed repo is laid out.
        "manifest_path": f"manifests/{deployment_name}.yaml" if deployment_name else None,
    }


def propose_fix_node(state: AgentState) -> dict:
    if state.get("diagnosis") is None:
        return {}

    diagnosis = diagnosis_from_dict(state["diagnosis"])
    proposal = propose_fix(
        diagnosis,
        state.get("logs"),
        state.get("revision_diff"),
        api_key=state["gemini_api_key"],
    )
    return {"proposal": proposal.model_dump()}


def human_approval_node(state: AgentState) -> dict:
    if state.get("proposal") is None:
        return {}

    decision = interrupt(
        {
            "question": "Approve opening a PR with this fix proposal?",
            "diagnosis": state["diagnosis"],
            "proposal": state["proposal"],
        }
    )
    return {"approved": bool(decision)}


def create_pr_node(state: AgentState) -> dict:
    if not state.get("approved"):
        return {"outcome": "Rejected by reviewer — no PR opened, no action taken anywhere."}

    if not state.get("manifest_path"):
        return {"outcome": "Approved, but no manifest_path resolved (deployment lookup failed) — cannot open a PR."}

    pr_url = open_remediation_pr(
        github_token=state["github_token"],
        repo_name=state["git_repo"],
        base_branch=state["git_base_branch"],
        manifest_path=state["manifest_path"],
        diagnosis=diagnosis_from_dict(state["diagnosis"]),
        proposal=FixProposal(**state["proposal"]),
    )
    return {"pr_url": pr_url, "outcome": f"PR opened: {pr_url}"}


def route_after_diagnosis(state: AgentState) -> str:
    return "propose_fix" if state.get("diagnosis") else END


def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("diagnose", diagnose_node)
    builder.add_node("propose_fix", propose_fix_node)
    builder.add_node("human_approval", human_approval_node)
    builder.add_node("create_pr", create_pr_node)

    builder.add_edge(START, "diagnose")
    builder.add_conditional_edges("diagnose", route_after_diagnosis, {"propose_fix": "propose_fix", END: END})
    builder.add_edge("propose_fix", "human_approval")
    builder.add_edge("human_approval", "create_pr")
    builder.add_edge("create_pr", END)

    return builder.compile(checkpointer=_Saver())