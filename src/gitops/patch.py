"""Gemini's proposed_yaml_patch is deliberately partial (just the fields
that should change), not a full manifest — merging it onto the real file is
this module's job. Uses PyYAML's safe_load/safe_dump, which means comments
and key ordering in the original file are NOT preserved. That's a real
tradeoff (ruamel.yaml would preserve them at the cost of another dependency
and more complexity) — documented in the README rather than solved here.
"""
from __future__ import annotations

import yaml


def _merge_containers(base_containers: list[dict], patch_containers: list[dict]) -> list[dict]:
    """Containers are a list, so a naive dict-merge would just clobber the
    whole list. Match by 'name' instead, the way a human editing the YAML
    by hand would reason about it.
    """
    merged = [dict(c) for c in base_containers]
    by_name = {c.get("name"): c for c in merged}

    for patch_container in patch_containers:
        name = patch_container.get("name")
        if name in by_name:
            _deep_merge(by_name[name], patch_container)
        else:
            merged.append(patch_container)

    return merged


def _deep_merge(base: dict, patch: dict) -> dict:
    for key, value in patch.items():
        if key == "containers" and isinstance(value, list) and isinstance(base.get(key), list):
            base[key] = _merge_containers(base[key], value)
        elif isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _normalize_escaped_newlines(text: str) -> str:
    """Gemini occasionally double-escapes newlines inside the JSON string
    field, so after JSON parsing the string still contains literal
    backslash-n text instead of real line breaks — yaml.safe_load then
    fails with a cryptic 'mapping values are not allowed here' error. This
    is a real observed model quirk (LLM output isn't fully deterministic,
    see README), not a hypothetical — normalize defensively before parsing.
    """
    return text.replace("\\r\\n", "\n").replace("\\n", "\n")


def apply_patch(base_manifest_yaml: str, patch_yaml: str) -> str:
    """Both inputs are YAML text. Returns the merged manifest as YAML text.
    Assumes a single-document manifest (a lone Deployment) — the failure
    scenarios this project targets are all single-Deployment files.
    """
    base = yaml.safe_load(base_manifest_yaml)

    try:
        patch = yaml.safe_load(_normalize_escaped_newlines(patch_yaml))
    except yaml.YAMLError as exc:
        raise ValueError(
            f"Could not parse the proposed YAML patch, even after newline "
            f"normalization. Raw patch text:\n{patch_yaml!r}"
        ) from exc

    if not isinstance(patch, dict):
        raise ValueError(f"Expected patch to be a YAML mapping, got: {type(patch)}")

    merged = _deep_merge(base, patch)
    return yaml.safe_dump(merged, sort_keys=False, default_flow_style=False)