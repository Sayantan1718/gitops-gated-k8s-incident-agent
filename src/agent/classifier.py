"""Maps a pod's container statuses to one of the bounded failure classes
this project targets. Kubernetes exposes failure state as terminated/waiting
reasons on each container, not as a single top-level field, so a pod with
multiple containers can carry more than one signal — we return the most
specific one we find.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum

from kubernetes.client import V1Pod, V1ContainerStatus


class FailureClass(str, Enum):
    OOM_KILLED = "oom_killed"
    CRASH_LOOP_BACKOFF = "crash_loop_backoff"
    IMAGE_PULL_BACKOFF = "image_pull_backoff"
    HPA_THRASH = "hpa_thrash"  # not detected here — see hpa.py, needs time-series data
    UNKNOWN = "unknown"


@dataclass
class PodDiagnosis:
    pod_name: str
    namespace: str
    container_name: str
    failure_class: FailureClass
    reason: str
    message: str | None
    restart_count: int


# last_state.terminated.reason values that map directly to a failure class.
_TERMINATED_REASON_MAP = {
    "OOMKilled": FailureClass.OOM_KILLED,
}

# current state.waiting.reason values, checked only if last_state didn't
# already give us something more specific (OOMKilled beats a generic
# CrashLoopBackOff, since OOM is the actual root cause).
_WAITING_REASON_MAP = {
    "CrashLoopBackOff": FailureClass.CRASH_LOOP_BACKOFF,
    "ImagePullBackOff": FailureClass.IMAGE_PULL_BACKOFF,
    "ErrImagePull": FailureClass.IMAGE_PULL_BACKOFF,
}


def _classify_container(status: V1ContainerStatus) -> tuple[FailureClass, str, str | None]:
    if status.last_state and status.last_state.terminated:
        reason = status.last_state.terminated.reason
        if reason in _TERMINATED_REASON_MAP:
            return _TERMINATED_REASON_MAP[reason], reason, status.last_state.terminated.message

    if status.state and status.state.waiting:
        reason = status.state.waiting.reason
        if reason in _WAITING_REASON_MAP:
            return _WAITING_REASON_MAP[reason], reason, status.state.waiting.message

    return FailureClass.UNKNOWN, "none", None


def classify_pod(pod: V1Pod) -> list[PodDiagnosis]:
    """Returns one PodDiagnosis per container that isn't healthy. Empty list
    means the pod looks fine — callers should skip it.
    """
    diagnoses: list[PodDiagnosis] = []
    statuses = pod.status.container_statuses or []

    for status in statuses:
        failure_class, reason, message = _classify_container(status)
        if failure_class is FailureClass.UNKNOWN:
            continue
        diagnoses.append(
            PodDiagnosis(
                pod_name=pod.metadata.name,
                namespace=pod.metadata.namespace,
                container_name=status.name,
                failure_class=failure_class,
                reason=reason,
                message=message,
                restart_count=status.restart_count,
            )
        )

    return diagnoses


def diagnosis_to_dict(diagnosis: PodDiagnosis) -> dict:
    """LangGraph's checkpointer only trusts plain dicts/lists/primitives for
    msgpack serialization — custom dataclasses get an 'unregistered type'
    deprecation warning today and will hard-fail in a future version. Use
    this at every point a PodDiagnosis enters graph state.
    """
    data = asdict(diagnosis)
    data["failure_class"] = diagnosis.failure_class.value
    return data


def diagnosis_from_dict(data: dict) -> PodDiagnosis:
    data = dict(data)
    data["failure_class"] = FailureClass(data["failure_class"])
    return PodDiagnosis(**data)