"""Asserts the agent's ServiceAccount cannot mutate cluster state.
Requires a live kind cluster with RBAC manifests applied — this is an
integration test, not a unit test; mark it accordingly so `pytest -m unit`
skips it in fast local loops.
"""
import pytest
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

KUBECONFIG_PATH = "configs/rbac/agent-kubeconfig.yaml"


@pytest.mark.integration
def test_agent_cannot_create_pods():
    config.load_kube_config(config_file=KUBECONFIG_PATH)
    v1 = client.CoreV1Api()

    with pytest.raises(ApiException) as exc_info:
        v1.create_namespaced_pod(
            namespace="default",
            body=client.V1Pod(
                metadata=client.V1ObjectMeta(name="rbac-boundary-probe"),
                spec=client.V1PodSpec(
                    containers=[client.V1Container(name="probe", image="busybox")]
                ),
            ),
        )
    assert exc_info.value.status == 403


@pytest.mark.integration
def test_agent_can_list_pods():
    config.load_kube_config(config_file=KUBECONFIG_PATH)
    v1 = client.CoreV1Api()
    # Should not raise.
    v1.list_namespaced_pod(namespace="default")