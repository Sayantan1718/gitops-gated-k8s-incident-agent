from unittest.mock import patch, MagicMock

from src.agent.classifier import PodDiagnosis, FailureClass
from src.agent.models import FixProposal
from src.agent.gemini_client import propose_fix, _build_prompt


def _sample_diagnosis() -> PodDiagnosis:
    return PodDiagnosis(
        pod_name="oom-demo-abc123",
        namespace="failure-lab",
        container_name="stress",
        failure_class=FailureClass.OOM_KILLED,
        reason="OOMKilled",
        message=None,
        restart_count=9,
    )


def test_prompt_includes_key_diagnostic_fields():
    prompt = _build_prompt(_sample_diagnosis(), logs="allocating memory", revision_diff=None)

    assert "oom_killed" in prompt
    assert "OOMKilled" in prompt
    assert "restart count: 9" in prompt.lower() or "Restart count: 9" in prompt
    assert "allocating memory" in prompt


def test_prompt_notes_missing_logs_explicitly():
    prompt = _build_prompt(_sample_diagnosis(), logs=None, revision_diff=None)

    assert "No container logs were captured" in prompt


@patch("src.agent.gemini_client.genai.Client")
def test_propose_fix_parses_structured_response(mock_client_cls):
    mock_proposal = FixProposal(
        root_cause="Memory limit too low for the workload's actual usage.",
        confidence="high",
        reasoning="last_state.terminated.reason was OOMKilled with a 50Mi limit.",
        recommended_change_summary="Raise memory limit from 50Mi to 200Mi.",
        proposed_yaml_patch="resources:\n  limits:\n    memory: 200Mi",
        risk_notes="Verify 200Mi covers peak usage in production traffic, not just this synthetic test.",
    )

    mock_response = MagicMock()
    mock_response.parsed = mock_proposal
    mock_client_instance = MagicMock()
    mock_client_instance.models.generate_content.return_value = mock_response
    mock_client_cls.return_value = mock_client_instance

    result = propose_fix(_sample_diagnosis(), logs="oom log", revision_diff=None, api_key="fake-key")

    assert result == mock_proposal
    mock_client_cls.assert_called_once_with(api_key="fake-key")


@patch("src.agent.gemini_client.genai.Client")
def test_propose_fix_raises_on_unparseable_response(mock_client_cls):
    mock_response = MagicMock()
    mock_response.parsed = None
    mock_response.text = "not valid json"
    mock_client_instance = MagicMock()
    mock_client_instance.models.generate_content.return_value = mock_response
    mock_client_cls.return_value = mock_client_instance

    try:
        propose_fix(_sample_diagnosis(), logs=None, revision_diff=None, api_key="fake-key")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "not valid json" in str(exc)