from kubernetes.client import (
    V1Pod,
    V1ObjectMeta,
    V1PodStatus,
    V1ContainerStatus,
    V1ContainerState,
    V1ContainerStateWaiting,
    V1ContainerStateTerminated,
)

from src.agent.classifier import classify_pod, FailureClass


def _pod_with_status(*, waiting_reason=None, last_terminated_reason=None, restart_count=0) -> V1Pod:
    state = V1ContainerState(
        waiting=V1ContainerStateWaiting(reason=waiting_reason) if waiting_reason else None
    )
    last_state = V1ContainerState(
        terminated=V1ContainerStateTerminated(reason=last_terminated_reason, exit_code=1)
        if last_terminated_reason
        else None
    )
    status = V1ContainerStatus(
        name="app",
        image="busybox",
        image_id="",
        ready=False,
        restart_count=restart_count,
        state=state,
        last_state=last_state,
    )
    return V1Pod(
        metadata=V1ObjectMeta(name="test-pod", namespace="failure-lab"),
        status=V1PodStatus(container_statuses=[status]),
    )


def test_oom_killed_detected_from_last_state():
    pod = _pod_with_status(waiting_reason="CrashLoopBackOff", last_terminated_reason="OOMKilled", restart_count=5)
    diagnoses = classify_pod(pod)

    assert len(diagnoses) == 1
    # OOMKilled is the actual root cause, even though the pod is currently
    # sitting in CrashLoopBackOff waiting state — last_state wins.
    assert diagnoses[0].failure_class == FailureClass.OOM_KILLED
    assert diagnoses[0].restart_count == 5


def test_plain_crash_loop_without_oom():
    pod = _pod_with_status(waiting_reason="CrashLoopBackOff", last_terminated_reason="Error", restart_count=3)
    diagnoses = classify_pod(pod)

    assert len(diagnoses) == 1
    assert diagnoses[0].failure_class == FailureClass.CRASH_LOOP_BACKOFF


def test_image_pull_backoff():
    pod = _pod_with_status(waiting_reason="ImagePullBackOff")
    diagnoses = classify_pod(pod)

    assert len(diagnoses) == 1
    assert diagnoses[0].failure_class == FailureClass.IMAGE_PULL_BACKOFF


def test_err_image_pull_maps_to_same_class_as_backoff():
    pod = _pod_with_status(waiting_reason="ErrImagePull")
    diagnoses = classify_pod(pod)

    assert diagnoses[0].failure_class == FailureClass.IMAGE_PULL_BACKOFF


def test_healthy_pod_produces_no_diagnosis():
    # No waiting/terminated state set at all — this is what a normally
    # running container looks like (state.running would be populated instead,
    # which classify_pod doesn't inspect since it's not a failure signal).
    status = V1ContainerStatus(
        name="app", image="busybox", image_id="", ready=True, restart_count=0,
        state=V1ContainerState(),
    )
    pod = V1Pod(
        metadata=V1ObjectMeta(name="healthy-pod", namespace="failure-lab"),
        status=V1PodStatus(container_statuses=[status]),
    )
    assert classify_pod(pod) == []