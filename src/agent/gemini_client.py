"""Turns a PodDiagnosis + supporting evidence into a structured fix
proposal via Gemini. This node only ever produces a suggestion — nothing
here touches the cluster or git; see src/gitops for the PR-creation step
that a human then reviews.
"""
from __future__ import annotations

from google import genai
from google.genai import types

from src.agent.classifier import PodDiagnosis
from src.agent.models import FixProposal

# Pinned to the current stable Flash tier as of Aug 2026 (see README) rather
# than the `-latest` alias, which Google documents as pointing to an
# experimental build with tighter rate limits — wrong tradeoff for this.
MODEL_NAME = "gemini-3.6-flash"


def _build_prompt(diagnosis: PodDiagnosis, logs: str | None, revision_diff: dict | None) -> str:
    sections = [
        "You are diagnosing a Kubernetes pod failure. You have READ-ONLY access to "
        "this evidence — you cannot query the cluster further, so reason only from "
        "what's given below. Propose a fix as a config change, never as a suggestion "
        "to run commands against the live cluster.",
        "",
        f"Pod: {diagnosis.pod_name} (namespace: {diagnosis.namespace})",
        f"Container: {diagnosis.container_name}",
        f"Detected failure class: {diagnosis.failure_class.value}",
        f"Reason code: {diagnosis.reason}",
        f"Restart count: {diagnosis.restart_count}",
    ]

    if diagnosis.message:
        sections.append(f"Termination/waiting message: {diagnosis.message}")

    if logs:
        sections.append(f"\nLast known container logs (tail):\n{logs.strip()[-2000:]}")
    else:
        sections.append("\nNo container logs were captured (likely killed before flushing output).")

    if revision_diff and revision_diff.get("changes"):
        sections.append(
            f"\nThis Deployment changed between revision {revision_diff['previous_revision']} "
            f"and {revision_diff['current_revision']}. Treat any of these as a likely root "
            f"cause if it correlates with the failure:"
        )
        for change in revision_diff["changes"]:
            sections.append(f"  - {change}")
    elif revision_diff is not None:
        sections.append(
            "\nA previous revision exists but no container-level image/resource changes "
            "were detected between them."
        )
    else:
        sections.append(
            "\nNo previous revision was available to diff — reason from the current "
            "config and failure signal alone."
        )

    return "\n".join(sections)


def propose_fix(
    diagnosis: PodDiagnosis,
    logs: str | None,
    revision_diff: dict | None,
    api_key: str,
) -> FixProposal:
    client = genai.Client(api_key=api_key)
    prompt = _build_prompt(diagnosis, logs, revision_diff)

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=FixProposal,
            temperature=0.2,  # low but not zero — Gemini isn't fully deterministic even at temp 0
        ),
    )

    if response.parsed is None:
        raise ValueError(f"Gemini did not return a schema-conformant response: {response.text!r}")

    return response.parsed