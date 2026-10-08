from src.gitops.patch import apply_patch

BASE_MANIFEST = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: oom-demo
  namespace: failure-lab
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: stress
          image: polinux/stress
          resources:
            requests:
              memory: 20Mi
            limits:
              memory: 50Mi
"""


def test_patch_merges_matching_container_by_name():
    patch = """
spec:
  template:
    spec:
      containers:
        - name: stress
          resources:
            limits:
              memory: 200Mi
"""
    result = apply_patch(BASE_MANIFEST, patch)

    assert "memory: 200Mi" in result
    # Unrelated fields on the same container must survive the merge.
    assert "image: polinux/stress" in result
    assert "requests" in result


def test_patch_does_not_touch_unrelated_top_level_fields():
    patch = """
spec:
  template:
    spec:
      containers:
        - name: stress
          resources:
            limits:
              memory: 200Mi
"""
    result = apply_patch(BASE_MANIFEST, patch)

    assert "name: oom-demo" in result
    assert "replicas: 1" in result


def test_patch_targeting_nonexistent_container_appends_it():
    patch = """
spec:
  template:
    spec:
      containers:
        - name: sidecar
          image: busybox
"""
    result = apply_patch(BASE_MANIFEST, patch)

    assert "name: sidecar" in result
    assert "name: stress" in result  # original container still present


def test_patch_with_literal_escaped_newlines_still_parses():
    # This is exactly what Gemini produced in a real observed run: the JSON
    # string field contained literal backslash-n text instead of real
    # newlines, which yaml.safe_load can't parse without normalization.
    patch_with_literal_escapes = (
        "spec:\\n  template:\\n    spec:\\n      containers:\\n"
        "      - name: stress\\n        resources:\\n          limits:\\n"
        "            memory: 256Mi\\n          requests:\\n"
        "            memory: 128Mi"
    )

    result = apply_patch(BASE_MANIFEST, patch_with_literal_escapes)

    assert "memory: 256Mi" in result
    assert "memory: 128Mi" in result


def test_genuinely_unparseable_patch_raises_helpful_error():
    try:
        apply_patch(BASE_MANIFEST, "not: valid: yaml: [unclosed")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "Could not parse the proposed YAML patch" in str(exc)