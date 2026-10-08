from unittest.mock import patch, MagicMock

from src.agent.classifier import PodDiagnosis, FailureClass
from src.agent.models import FixProposal
from src.gitops.github_client import open_remediation_pr

BASE_MANIFEST = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: oom-demo
spec:
  template:
    spec:
      containers:
        - name: stress
          resources:
            limits:
              memory: 50Mi
"""


def _diagnosis() -> PodDiagnosis:
    return PodDiagnosis(
        pod_name="oom-demo-abc123",
        namespace="failure-lab",
        container_name="stress",
        failure_class=FailureClass.OOM_KILLED,
        reason="OOMKilled",
        message=None,
        restart_count=5,
    )


def _proposal() -> FixProposal:
    return FixProposal(
        root_cause="Memory limit too low.",
        confidence="high",
        reasoning="OOMKilled reason code observed.",
        recommended_change_summary="Raise memory limit to 200Mi.",
        proposed_yaml_patch="spec:\n  template:\n    spec:\n      containers:\n        - name: stress\n          resources:\n            limits:\n              memory: 200Mi",
        risk_notes="Verify node capacity.",
    )


@patch("src.gitops.github_client.Github")
def test_open_remediation_pr_creates_branch_commits_and_pr(mock_github_cls):
    mock_repo = MagicMock()
    mock_repo.get_branch.return_value.commit.sha = "base-sha-123"
    mock_repo.get_contents.return_value.decoded_content = BASE_MANIFEST.encode("utf-8")
    mock_repo.get_contents.return_value.sha = "file-sha-456"
    mock_repo.create_pull.return_value.html_url = "https://github.com/org/gitops-repo/pull/1"

    mock_github_cls.return_value.get_repo.return_value = mock_repo

    url = open_remediation_pr(
        github_token="fake-token",
        repo_name="org/gitops-repo",
        base_branch="main",
        manifest_path="manifests/oom-demo.yaml",
        diagnosis=_diagnosis(),
        proposal=_proposal(),
    )

    assert url == "https://github.com/org/gitops-repo/pull/1"

    # A branch was cut from main's current commit, not created out of thin air.
    mock_repo.create_git_ref.assert_called_once()
    ref_kwargs = mock_repo.create_git_ref.call_args.kwargs
    assert ref_kwargs["sha"] == "base-sha-123"
    assert ref_kwargs["ref"].startswith("refs/heads/incident-agent/oom-demo-abc123")

    # The committed content actually reflects the merged patch, not the raw original.
    update_kwargs = mock_repo.update_file.call_args.kwargs
    assert "memory: 200Mi" in update_kwargs["content"]
    assert update_kwargs["sha"] == "file-sha-456"

    # PR body carries the reasoning trace, not just a bare diff.
    pr_kwargs = mock_repo.create_pull.call_args.kwargs
    assert "OOMKilled reason code observed" in pr_kwargs["body"]
    assert "human must review and merge" in pr_kwargs["body"]


@patch("src.gitops.github_client.Github")
def test_pr_creation_failure_raises_with_branch_name_context(mock_github_cls):
    from github.GithubException import GithubException

    mock_repo = MagicMock()
    mock_repo.get_branch.return_value.commit.sha = "base-sha-123"
    mock_repo.get_contents.return_value.decoded_content = BASE_MANIFEST.encode("utf-8")
    mock_repo.get_contents.return_value.sha = "file-sha-456"
    mock_repo.create_pull.side_effect = GithubException(422, {"message": "validation failed"}, None)

    mock_github_cls.return_value.get_repo.return_value = mock_repo

    try:
        open_remediation_pr(
            github_token="fake-token",
            repo_name="org/gitops-repo",
            base_branch="main",
            manifest_path="manifests/oom-demo.yaml",
            diagnosis=_diagnosis(),
            proposal=_proposal(),
        )
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "PR creation failed" in str(exc)
