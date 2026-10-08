# Project: GitOps-Gated Kubernetes Incident Remediation Agent

## Goal
Detect a bounded set of known Kubernetes failure classes (OOMKilled, CrashLoopBackOff,
ImagePullBackOff, HPA thrashing), correlate the failure with recent deploys, and propose a fix
as a **GitOps pull request** — never a direct `kubectl apply` against the live cluster. A human
merges the PR to apply the fix.

## Why This Matters (recruiter framing)
This mirrors the 2026 industry-accepted pattern for safe AI SRE agents: LLM reasoning bounded by
GitOps and policy, not raw cluster write access. Building it this way (vs. a demo that runs
`kubectl` directly) is the difference between a toy and a design a platform team would actually
trust.

## Stack (pin exact versions before coding)
- LangGraph — bounded diagnosis → propose → gated-commit flow. Reuses the interrupt/approval
  pattern from the self-healing DevOps agent project. Verify current interrupt/resume API before
  implementing.
- FastAPI — read-only diagnostic API + webhook receiver for cluster events
- `kubernetes` Python client — **read-only** cluster access only (list events, get pod status,
  read logs). No write/patch/delete verbs granted to the agent's service account.
- Git provider API (GitHub/GitLab) — creates the remediation PR
- Prometheus + Kubernetes events — signal sources for failure detection
- Gemini API (gemini-3.6-flash) — root-cause correlation + fix proposal generation

## Architecture (high level)
1. Watch Kubernetes events / Prometheus alerts for one of the bounded failure classes
2. Diagnosis node: pull relevant logs, recent deploy history (git log/diff), pod spec
3. Gemini call: classify likely root cause, propose a concrete manifest/config change
4. Git node: open a PR with the proposed change, annotated with the agent's reasoning
5. Interrupt: agent stops here — merge is a human action, not an agent action
6. On merge (via CI/CD or GitOps controller like Argo CD/Flux): change applies normally

## Achievement Criteria (Definition of Done)
- [ ] Correctly detects and classifies at least 3 of the 4 target failure classes from
      simulated/injected cluster events
- [ ] Agent's Kubernetes service account has **read-only** RBAC — verified explicitly, not assumed
- [ ] No direct cluster mutation anywhere in the code path — all fixes go through a Git PR
- [ ] PR body includes the agent's reasoning trace (what it saw, why it concluded X, confidence)
- [ ] At least one full failure→diagnose→PR→human-merge cycle demoed end-to-end
- [ ] Unit tests for: failure classifier, RBAC permission boundary (test that write calls are
      rejected), PR generation logic
- [ ] README explicitly states which crawl-walk-run stage this reaches (suggest-only, in this
      case — do not claim auto-remediation without a human gate)
- [ ] No secrets committed; Git provider token and cluster credentials via `.env` + `.env.example`
- [ ] Dependencies pinned; docker-compose or kind/minikube setup documented for local testing

## Git / Documentation Reminders
- Structure: `src/`, `tests/`, `configs/`, `README.md`, `LICENSE`
- README must cover: problem, approach, architecture diagram, setup, exact run commands
  (including how to spin up a local kind/minikube cluster for testing), the bounded failure-class
  list, results/limitations, license
- Explicitly document the RBAC policy used for the agent's service account (include the actual
  YAML) — this is the single most scrutinized detail in a public repo for this kind of project
- Cite the GitOps-gated agent pattern as reflecting current industry practice, not a novel
  invention, if referencing specific tools/patterns you read about
- Commit incrementally; tag a release once the full detect→PR cycle works on a local test cluster
- Include a sample generated PR (screenshot or markdown export) in the repo so the output quality
  is inspectable without running the whole stack
