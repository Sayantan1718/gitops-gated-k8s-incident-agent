"""Thin wrapper around the official kubernetes client, scoped to the reads
this agent needs: unhealthy pods, their logs, and what changed in the owning
Deployment's last revision. Every call here maps to a verb granted in
configs/rbac/cluster-role.yaml — nothing here can mutate cluster state.
"""
from __future__ import annotations

from dataclasses import dataclass

from kubernetes import client, config
from kubernetes.client import V1Pod, V1Deployment, V1PodTemplateSpec
from kubernetes.client.exceptions import ApiException

from src.agent.classifier import PodDiagnosis, classify_pod


def load_agent_client(kubeconfig_path: str) -> None:
    """Call once at startup. Subsequent client.CoreV1Api()/AppsV1Api() calls
    use whatever context this kubeconfig points at.
    """
    config.load_kube_config(config_file=kubeconfig_path)


def list_unhealthy_pods(namespace: str) -> list[PodDiagnosis]:
    v1 = client.CoreV1Api()
    pods: list[V1Pod] = v1.list_namespaced_pod(namespace=namespace).items

    diagnoses: list[PodDiagnosis] = []
    for pod in pods:
        diagnoses.extend(classify_pod(pod))
    return diagnoses


def _is_log_unavailable(log_text: str) -> bool:
    """containerd returns this as normal 200 response text (not an
    exception) when a container was killed before it could flush any log
    output — happens constantly with fast OOM kills. Without this check,
    that error string gets fed to the LLM as if it were real log content.
    """
    return log_text.strip().startswith("unable to retrieve container logs")


def get_pod_logs(namespace: str, pod_name: str, container: str, tail_lines: int = 50) -> str | None:
    """Pulls the CURRENT container's logs. For a crashed/restarted container
    you almost always want get_previous_pod_logs instead — the current
    attempt may not have logged anything useful yet. Returns None if no
    logs were actually captured (see _is_log_unavailable).
    """
    v1 = client.CoreV1Api()
    logs = v1.read_namespaced_pod_log(
        name=pod_name, namespace=namespace, container=container, tail_lines=tail_lines
    )
    return None if _is_log_unavailable(logs) else logs


def get_previous_pod_logs(namespace: str, pod_name: str, container: str, tail_lines: int = 50) -> str | None:
    """Logs from the last terminated attempt — this is what actually
    explains an OOMKill or crash, since the current attempt just started.
    Returns None if there's no previous attempt yet, or if nothing was
    captured before the container was killed.
    """
    v1 = client.CoreV1Api()
    try:
        logs = v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container=container,
            tail_lines=tail_lines,
            previous=True,
        )
    except ApiException as exc:
        if exc.status == 400:  # "previous terminated container not found"
            return None
        raise
    return None if _is_log_unavailable(logs) else logs


def get_owning_deployment(namespace: str, pod: V1Pod) -> V1Deployment | None:
    apps_v1 = client.AppsV1Api()

    rs_ref = next((ref for ref in (pod.metadata.owner_references or []) if ref.kind == "ReplicaSet"), None)
    if rs_ref is None:
        return None

    rs = apps_v1.read_namespaced_replica_set(name=rs_ref.name, namespace=namespace)
    deploy_ref = next((ref for ref in (rs.metadata.owner_references or []) if ref.kind == "Deployment"), None)
    if deploy_ref is None:
        return None

    return apps_v1.read_namespaced_deployment(name=deploy_ref.name, namespace=namespace)


@dataclass
class RevisionDiff:
    deployment_name: str
    current_revision: str
    previous_revision: str | None
    current_template: V1PodTemplateSpec
    previous_template: V1PodTemplateSpec | None


def get_revision_diff(namespace: str, deployment_name: str) -> RevisionDiff | None:
    """Every Deployment update leaves its old ReplicaSet around (scaled to 0)
    with a `deployment.kubernetes.io/revision` annotation, so we can compare
    the current pod template against the one before it without needing a
    real git-backed GitOps repo in this local setup — see README for the
    tradeoff this makes vs. diffing actual git history.
    """
    apps_v1 = client.AppsV1Api()
    all_rs = apps_v1.list_namespaced_replica_set(
        namespace=namespace,
        label_selector=f"app={deployment_name}",
    ).items

    def revision(rs) -> int:
        return int(rs.metadata.annotations.get("deployment.kubernetes.io/revision", "0"))

    owned = [rs for rs in all_rs if any(ref.kind == "Deployment" and ref.name == deployment_name for ref in (rs.metadata.owner_references or []))]
    if not owned:
        return None

    owned.sort(key=revision, reverse=True)
    current = owned[0]
    previous = owned[1] if len(owned) > 1 else None

    return RevisionDiff(
        deployment_name=deployment_name,
        current_revision=str(revision(current)),
        previous_revision=str(revision(previous)) if previous else None,
        current_template=current.spec.template,
        previous_template=previous.spec.template if previous else None,
    )


def summarize_revision_diff(diff: RevisionDiff) -> dict | None:
    """Converts a RevisionDiff (which holds raw kubernetes SDK objects) into
    a plain dict of just the container-level changes. Required before this
    can enter LangGraph state — the checkpointer serializes every state
    value via msgpack, and SDK objects like V1PodTemplateSpec aren't
    serializable. Plain dicts/strings always are.
    """
    if diff.previous_template is None:
        return None

    changes: list[dict] = []
    prev_by_name = {c.name: c for c in diff.previous_template.spec.containers}

    for cur_c in diff.current_template.spec.containers:
        prev_c = prev_by_name.get(cur_c.name)
        if prev_c is None:
            changes.append({"container": cur_c.name, "change": "new container in this revision"})
            continue
        if prev_c.image != cur_c.image:
            changes.append({
                "container": cur_c.name,
                "field": "image",
                "before": prev_c.image,
                "after": cur_c.image,
            })
        if prev_c.resources != cur_c.resources:
            changes.append({
                "container": cur_c.name,
                "field": "resources",
                "before": prev_c.resources.to_dict() if prev_c.resources else None,
                "after": cur_c.resources.to_dict() if cur_c.resources else None,
            })

    return {
        "deployment_name": diff.deployment_name,
        "previous_revision": diff.previous_revision,
        "current_revision": diff.current_revision,
        "changes": changes,
    }