"""End-to-end run: detect -> diagnose -> propose -> PAUSE for human approval
in the terminal -> open PR (or stop, if rejected).

Usage: python scripts/run_agent.py [namespace]
Requires GEMINI_API_KEY, GIT_TOKEN, GIT_REPO, GIT_BASE_BRANCH in .env.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
from langgraph.types import Command

from src.k8s.client import load_agent_client
from src.agent.graph import build_graph

load_dotenv()

REQUIRED_ENV = ["GEMINI_API_KEY", "GIT_TOKEN", "GIT_REPO", "GIT_BASE_BRANCH"]


def main() -> None:
    missing = [v for v in REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        raise SystemExit(f"Missing required env vars: {', '.join(missing)} — check your .env")

    namespace = sys.argv[1] if len(sys.argv) > 1 else "failure-lab"
    load_agent_client(os.environ.get("KUBECONFIG_PATH", "configs/rbac/agent-kubeconfig.yaml"))

    graph = build_graph()
    thread_config = {"configurable": {"thread_id": f"incident-{namespace}"}}

    initial_state = {
        "namespace": namespace,
        "gemini_api_key": os.environ["GEMINI_API_KEY"],
        "github_token": os.environ["GIT_TOKEN"],
        "git_repo": os.environ["GIT_REPO"],
        "git_base_branch": os.environ["GIT_BASE_BRANCH"],
    }

    result = graph.invoke(initial_state, thread_config)

    if "__interrupt__" not in result:
        # No unhealthy pod was found — diagnose_node short-circuited to END.
        print(result.get("outcome", "Graph finished without reaching human approval."))
        return

    payload = result["__interrupt__"][0].value
    proposal = payload["proposal"]
    diagnosis = payload["diagnosis"]

    print("=" * 70)
    print(f"Pod:            {diagnosis['pod_name']}")
    print(f"Failure class:  {diagnosis['failure_class']}")
    print(f"\nRoot cause ({proposal['confidence']} confidence): {proposal['root_cause']}")
    print(f"\nProposed change: {proposal['recommended_change_summary']}")
    print(f"\n{proposal['proposed_yaml_patch']}")
    print(f"\nRisk notes: {proposal['risk_notes']}")
    print("=" * 70)

    answer = input("\nOpen a PR with this fix? [y/N]: ").strip().lower()
    final_result = graph.invoke(Command(resume=(answer == "y")), thread_config)

    print(f"\n{final_result.get('outcome')}")


if __name__ == "__main__":
    main()