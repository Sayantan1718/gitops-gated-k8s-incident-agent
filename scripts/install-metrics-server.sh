#!/usr/bin/env bash
# kind's kubelet uses self-signed certs metrics-server doesn't trust by
# default, so we patch in --kubelet-insecure-tls after install. This is a
# local-dev-only relaxation — do not carry this patch into a real cluster.
set -euo pipefail

kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

kubectl patch deployment metrics-server -n kube-system --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]'

echo "Waiting for metrics-server to become ready..."
kubectl -n kube-system rollout status deployment/metrics-server --timeout=120s

echo "Verifying (may take ~1 min to populate on a fresh cluster):"
kubectl top nodes || echo "metrics not populated yet — retry 'kubectl top nodes' in a minute"
