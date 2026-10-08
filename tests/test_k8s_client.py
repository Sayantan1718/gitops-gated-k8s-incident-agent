from unittest.mock import patch, MagicMock

from src.k8s.client import get_pod_logs, get_previous_pod_logs


@patch("src.k8s.client.client.CoreV1Api")
def test_get_pod_logs_returns_none_when_containerd_reports_unavailable(mock_api_cls):
    mock_api = MagicMock()
    mock_api.read_namespaced_pod_log.return_value = (
        "unable to retrieve container logs for containerd://abc123"
    )
    mock_api_cls.return_value = mock_api

    result = get_pod_logs(namespace="failure-lab", pod_name="oom-demo", container="stress")

    assert result is None


@patch("src.k8s.client.client.CoreV1Api")
def test_get_pod_logs_returns_text_when_real_logs_present(mock_api_cls):
    mock_api = MagicMock()
    mock_api.read_namespaced_pod_log.return_value = "starting up\nallocating memory\n"
    mock_api_cls.return_value = mock_api

    result = get_pod_logs(namespace="failure-lab", pod_name="oom-demo", container="stress")

    assert result == "starting up\nallocating memory\n"


@patch("src.k8s.client.client.CoreV1Api")
def test_get_previous_pod_logs_returns_none_when_unavailable(mock_api_cls):
    mock_api = MagicMock()
    mock_api.read_namespaced_pod_log.return_value = (
        "unable to retrieve container logs for containerd://abc123"
    )
    mock_api_cls.return_value = mock_api

    result = get_previous_pod_logs(namespace="failure-lab", pod_name="oom-demo", container="stress")

    assert result is None