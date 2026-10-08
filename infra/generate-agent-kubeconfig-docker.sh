#!/usr/bin/env bash
# Docker-network variant of generate-agent-kubeconfig.sh -- see the .ps1
# version's comments for why this is needed (127.0.0.1 inside a container
# isn't the host machine).
set -euo pipefail

CLUSTER_NAME="kind-incident-agent-dev"
CONTROL_PLANE_CONTAINER="incident-agent-dev-control-plane"
NAMESPACE="default"
SECRET_NAME="incident-agent-token"
OUT_FILE="configs/rbac/agent-kubeconfig-docker.yaml"

CA_DATA=$(kubectl config view --raw -o jsonpath="{.clusters[?(@.name=='${CLUSTER_NAME}')].cluster.certificate-authority-data}")

TOKEN=""
for i in {1..10}; do
  TOKEN=$(kubectl -n "${NAMESPACE}" get secret "${SECRET_NAME}" -o jsonpath="{.data.token}" 2>/dev/null | base64 -d || true)
  [[ -n "${TOKEN}" ]] && break
  sleep 1
done
if [[ -z "${TOKEN}" ]]; then
  echo "Token never populated — is configs/rbac/service-account.yaml applied?"
  exit 1
fi

cat > "${OUT_FILE}" <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: ${CLUSTER_NAME}
    cluster:
      server: https://${CONTROL_PLANE_CONTAINER}:6443
      certificate-authority-data: ${CA_DATA}
contexts:
  - name: incident-agent-context
    context:
      cluster: ${CLUSTER_NAME}
      namespace: ${NAMESPACE}
      user: incident-agent
current-context: incident-agent-context
users:
  - name: incident-agent
    user:
      token: ${TOKEN}
EOF

echo "Wrote ${OUT_FILE} (server: https://${CONTROL_PLANE_CONTAINER}:6443)"
