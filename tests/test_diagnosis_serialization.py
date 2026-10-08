"""Regression test: PodDiagnosis (a dataclass with an Enum field) triggered
an 'unregistered type' deprecation warning from LangGraph's checkpointer
when stored directly in graph state. diagnosis_to_dict/from_dict must
round-trip cleanly through plain dicts and real msgpack.
"""
import msgpack

from src.agent.classifier import PodDiagnosis, FailureClass, diagnosis_to_dict, diagnosis_from_dict


def test_diagnosis_round_trips_through_dict():
    original = PodDiagnosis(
        pod_name="oom-demo-abc",
        namespace="failure-lab",
        container_name="stress",
        failure_class=FailureClass.OOM_KILLED,
        reason="OOMKilled",
        message=None,
        restart_count=9,
    )

    as_dict = diagnosis_to_dict(original)
    assert as_dict["failure_class"] == "oom_killed"  # plain string, not the Enum member

    restored = diagnosis_from_dict(as_dict)
    assert restored == original


def test_diagnosis_dict_is_msgpack_serializable():
    original = PodDiagnosis(
        pod_name="oom-demo-abc",
        namespace="failure-lab",
        container_name="stress",
        failure_class=FailureClass.OOM_KILLED,
        reason="OOMKilled",
        message=None,
        restart_count=9,
    )

    packed = msgpack.packb(diagnosis_to_dict(original))
    unpacked = msgpack.unpackb(packed)
    assert diagnosis_from_dict(unpacked) == original
