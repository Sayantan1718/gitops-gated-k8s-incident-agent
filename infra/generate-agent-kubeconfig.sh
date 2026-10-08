#!/usr/bin/env bash
# Builds configs/rbac/agent-kubeconfig.yaml bound to the incident-agent
# ServiceAccount — this is the ONLY credential the agent process ever sees.
set -euo pipefail

CLUSTER_NAME="kind-incident-agent-dev"
NAMESPACE="default"
SECRET_NAME="incident-agent-token"
OUT_FILE="configs/rbac/agent-kubeconfig.yaml"

SERVER=$(kubectl config view --raw -o jsonpath="{.clusters[?(@.name=='${CLUSTER_NAME}')].cluster.server}")
CA_DATA=$(kubectl config view --raw -o jsonpath="{.clusters[?(@.name=='${CLUSTER_NAME}')].cluster.certificate-authority-data}")

# Wait for the token Secret to be populated by the controller.
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
      server: ${SERVER}
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

echo "Wrote ${OUT_FILE}"
