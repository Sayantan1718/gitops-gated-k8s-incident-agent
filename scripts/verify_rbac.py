"""One-off manual check: confirms the agent's ServiceAccount can read
pods but is rejected on a write call. Run after generating the kubeconfig.

Usage: python scripts/verify_rbac.py
"""
from __future__ import annotations

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

KUBECONFIG_PATH = "configs/rbac/agent-kubeconfig.yaml"


def main() -> None:
    config.load_kube_config(config_file=KUBECONFIG_PATH)
    v1 = client.CoreV1Api()

    pods = v1.list_namespaced_pod(namespace="default")
    print(f"[read OK] listed {len(pods.items)} pod(s) in 'default'")

    try:
        v1.create_namespaced_pod(
            namespace="default",
            body=client.V1Pod(
                metadata=client.V1ObjectMeta(name="rbac-boundary-probe"),
                spec=client.V1PodSpec(
                    containers=[client.V1Container(name="probe", image="busybox")]
                ),
            ),
        )
        raise SystemExit("[FAIL] write call succeeded — RBAC is NOT read-only!")
    except ApiException as exc:
        if exc.status == 403:
            print("[write blocked OK] create_namespaced_pod correctly returned 403 Forbidden")
        else:
            raise SystemExit(f"[FAIL] unexpected status {exc.status}: {exc.reason}")


if __name__ == "__main__":
    main()