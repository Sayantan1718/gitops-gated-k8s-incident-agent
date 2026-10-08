"""Manual test harness for Phase 6 — chains the Phase 5 diagnosis output
straight into Gemini and prints the resulting fix proposal. Not wired into
LangGraph yet; that's Phase 7, once PR creation exists to actually act on
this output.

Usage: python scripts/propose_fix.py [namespace]
Requires GEMINI_API_KEY in your environment (see .env.example).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

from src.k8s.client import (
    load_agent_client,
    list_unhealthy_pods,
    get_previous_pod_logs,
    get_pod_logs,
    get_owning_deployment,
    get_revision_diff,
    summarize_revision_diff,
)
from src.agent.gemini_client import propose_fix
from kubernetes import client as k8s_client

load_dotenv()

KUBECONFIG_PATH = os.environ.get("KUBECONFIG_PATH", "configs/rbac/agent-kubeconfig.yaml")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


def main() -> None:
    if not GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY not set — copy .env.example to .env and fill it in.")

    namespace = sys.argv[1] if len(sys.argv) > 1 else "failure-lab"
    load_agent_client(KUBECONFIG_PATH)

    diagnoses = list_unhealthy_pods(namespace)
    if not diagnoses:
        print(f"No unhealthy pods found in namespace '{namespace}'.")
        return

    v1 = k8s_client.CoreV1Api()
    diag = diagnoses[0]  # Phase 6 handles one at a time; batching comes with the LangGraph loop in Phase 7
    print(f"Diagnosing {diag.pod_name} ({diag.failure_class.value})...\n")

    logs = get_previous_pod_logs(namespace, diag.pod_name, diag.container_name)
    if logs is None:
        logs = get_pod_logs(namespace, diag.pod_name, diag.container_name)

    pod = v1.read_namespaced_pod(name=diag.pod_name, namespace=namespace)
    deployment = get_owning_deployment(namespace, pod)
    raw_diff = get_revision_diff(namespace, deployment.metadata.name) if deployment else None
    revision_diff = summarize_revision_diff(raw_diff) if raw_diff else None

    proposal = propose_fix(diag, logs, revision_diff, api_key=GEMINI_API_KEY)

    print("=" * 70)
    print(f"Root cause ({proposal.confidence} confidence): {proposal.root_cause}")
    print(f"\nReasoning:\n{proposal.reasoning}")
    print(f"\nRecommended change:\n{proposal.recommended_change_summary}")
    print(f"\nProposed patch:\n{proposal.proposed_yaml_patch}")
    print(f"\nRisk notes:\n{proposal.risk_notes}")


if __name__ == "__main__":
    main()