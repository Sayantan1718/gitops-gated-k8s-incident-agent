"""Manual test harness for Phase 5 — run this after injecting a failure
scenario to see exactly what the diagnosis layer would hand to the LLM in
Phase 6. Not wired into LangGraph yet.

Usage: python scripts/scan_cluster.py [namespace]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.k8s.client import (
    load_agent_client,
    list_unhealthy_pods,
    get_previous_pod_logs,
    get_pod_logs,
    get_owning_deployment,
    get_revision_diff,
)
from kubernetes import client as k8s_client

KUBECONFIG_PATH = os.environ.get("KUBECONFIG_PATH", "configs/rbac/agent-kubeconfig.yaml")


def main() -> None:
    namespace = sys.argv[1] if len(sys.argv) > 1 else "failure-lab"
    load_agent_client(KUBECONFIG_PATH)

    diagnoses = list_unhealthy_pods(namespace)
    if not diagnoses:
        print(f"No unhealthy pods found in namespace '{namespace}'.")
        return

    v1 = k8s_client.CoreV1Api()

    for diag in diagnoses:
        print("=" * 70)
        print(f"pod:            {diag.pod_name}")
        print(f"container:      {diag.container_name}")
        print(f"failure class:  {diag.failure_class.value}")
        print(f"reason:         {diag.reason}")
        print(f"restart count:  {diag.restart_count}")

        logs = get_previous_pod_logs(namespace, diag.pod_name, diag.container_name)
        if logs is None:
            logs = get_pod_logs(namespace, diag.pod_name, diag.container_name)
        if logs is None:
            print("--- no logs available (container killed before flushing output — common for fast OOM kills) ---")
        else:
            print(f"--- last logs (tail) ---\n{logs.strip()[-1000:]}")

        pod = v1.read_namespaced_pod(name=diag.pod_name, namespace=namespace)
        deployment = get_owning_deployment(namespace, pod)
        if deployment is None:
            print("--- no owning Deployment found (bare pod?) ---")
            continue

        diff = get_revision_diff(namespace, deployment.metadata.name)
        if diff is None or diff.previous_template is None:
            print(f"--- deployment '{deployment.metadata.name}' has no previous revision to diff ---")
            continue

        print(f"--- revision diff: {deployment.metadata.name} rev {diff.previous_revision} -> {diff.current_revision} ---")
        for cur_c in diff.current_template.spec.containers:
            prev_c = next((c for c in diff.previous_template.spec.containers if c.name == cur_c.name), None)
            if prev_c is None:
                print(f"  container '{cur_c.name}' is new in this revision")
                continue
            if prev_c.image != cur_c.image:
                print(f"  image changed: {prev_c.image} -> {cur_c.image}")
            if prev_c.resources != cur_c.resources:
                print(f"  resources changed: {prev_c.resources} -> {cur_c.resources}")


if __name__ == "__main__":
    main()