"""Regression test for a real bug: passing the raw RevisionDiff (which
wraps kubernetes SDK objects) into LangGraph state crashed the checkpointer
with 'Type is not msgpack serializable'. summarize_revision_diff() must
always produce plain-old-data — this test catches it if that ever regresses.
"""
import msgpack

from src.k8s.client import summarize_revision_diff, RevisionDiff
from kubernetes.client import V1PodTemplateSpec, V1PodSpec, V1Container, V1ResourceRequirements


def _template(image: str, memory_limit: str) -> V1PodTemplateSpec:
    return V1PodTemplateSpec(
        spec=V1PodSpec(
            containers=[
                V1Container(
                    name="stress",
                    image=image,
                    resources=V1ResourceRequirements(limits={"memory": memory_limit}),
                )
            ]
        )
    )


def test_summary_is_plain_data_and_msgpack_serializable():
    diff = RevisionDiff(
        deployment_name="oom-demo",
        current_revision="2",
        previous_revision="1",
        current_template=_template("polinux/stress", "200Mi"),
        previous_template=_template("polinux/stress", "50Mi"),
    )

    summary = summarize_revision_diff(diff)

    assert summary["deployment_name"] == "oom-demo"
    assert any(c["field"] == "resources" for c in summary["changes"])

    # The actual regression check: this must not raise.
    packed = msgpack.packb(summary)
    assert msgpack.unpackb(packed) == summary


def test_summary_is_none_when_no_previous_revision():
    diff = RevisionDiff(
        deployment_name="oom-demo",
        current_revision="1",
        previous_revision=None,
        current_template=_template("polinux/stress", "50Mi"),
        previous_template=None,
    )

    assert summarize_revision_diff(diff) is None