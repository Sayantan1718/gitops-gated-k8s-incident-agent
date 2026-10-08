"""Opens a PR against the GitOps config repo. This is the only place in the
whole agent that writes anything, anywhere — and it writes to a git branch,
never to the cluster. A human still has to click merge for the change to
take effect.
"""
from __future__ import annotations

import time

from github import Github, Auth
from github.GithubException import GithubException

from src.agent.classifier import PodDiagnosis
from src.agent.models import FixProposal
from src.gitops.patch import apply_patch


def _build_pr_body(diagnosis: PodDiagnosis, proposal: FixProposal) -> str:
    return f"""## Automated incident remediation proposal

**This PR was opened by an automated agent. It has read-only access to the \
cluster and cannot merge this itself — a human must review and merge.**

### What it saw
- Pod: `{diagnosis.pod_name}` (namespace `{diagnosis.namespace}`)
- Container: `{diagnosis.container_name}`
- Failure class: `{diagnosis.failure_class.value}`
- Reason code: `{diagnosis.reason}`
- Restart count: {diagnosis.restart_count}

### Root cause ({proposal.confidence} confidence)
{proposal.root_cause}

### Reasoning
{proposal.reasoning}

### Proposed change
{proposal.recommended_change_summary}

```yaml
{proposal.proposed_yaml_patch}
```

### Risk notes
{proposal.risk_notes}

---
_Review the diff below carefully before merging — this is a suggestion, \
not a verified fix._
"""


def open_remediation_pr(
    github_token: str,
    repo_name: str,
    base_branch: str,
    manifest_path: str,
    diagnosis: PodDiagnosis,
    proposal: FixProposal,
) -> str:
    """Returns the URL of the created PR. Raises on any GitHub API failure —
    callers should not silently swallow this, a failed PR means the
    incident was diagnosed but nothing was actually proposed anywhere.
    """
    gh = Github(auth=Auth.Token(github_token))
    repo = gh.get_repo(repo_name)

    base_sha = repo.get_branch(base_branch).commit.sha
    branch_name = f"incident-agent/{diagnosis.pod_name}-{int(time.time())}"
    repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_sha)

    existing_file = repo.get_contents(manifest_path, ref=base_branch)
    current_content = existing_file.decoded_content.decode("utf-8")
    patched_content = apply_patch(current_content, proposal.proposed_yaml_patch)

    repo.update_file(
        path=manifest_path,
        message=f"Fix {diagnosis.failure_class.value} in {diagnosis.pod_name}",
        content=patched_content,
        sha=existing_file.sha,
        branch=branch_name,
    )

    try:
        pr = repo.create_pull(
            title=f"[incident-agent] Fix {diagnosis.failure_class.value} in {diagnosis.pod_name}",
            body=_build_pr_body(diagnosis, proposal),
            head=branch_name,
            base=base_branch,
        )
    except GithubException as exc:
        raise RuntimeError(f"Branch '{branch_name}' was created but PR creation failed: {exc}") from exc

    return pr.html_url
