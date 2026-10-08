# Docker-network variant of generate-agent-kubeconfig.ps1. The regular
# kubeconfig points at https://127.0.0.1:<kind's host-mapped port>, which
# only resolves from the HOST machine -- inside a container, 127.0.0.1 means
# the container itself. kind's control-plane node is reachable by container
# name on the internal 'kind' Docker network at its real port, 6443, which
# works identically regardless of what host port kind happened to map.
$ErrorActionPreference = "Stop"

$ClusterName = "kind-incident-agent-dev"
$ControlPlaneContainer = "incident-agent-dev-control-plane"
$Namespace   = "default"
$SecretName  = "incident-agent-token"
$OutFile     = "configs/rbac/agent-kubeconfig-docker.yaml"

# Reuse the same CA cert kind already generated -- it's signed with the
# control-plane container name as a valid SAN, so TLS verification still
# works when connecting via that name instead of 127.0.0.1.
$CaData = kubectl config view --raw -o "jsonpath={.clusters[?(@.name=='$ClusterName')].cluster.certificate-authority-data}"

if (-not $CaData) {
    Write-Error "Could not read cluster '$ClusterName' from kubeconfig. Run 'kubectl config get-contexts' to check."
    exit 1
}

$Token = $null
for ($i = 0; $i -lt 10; $i++) {
    $TokenB64 = kubectl -n $Namespace get secret $SecretName -o "jsonpath={.data.token}" 2>$null
    if ($TokenB64) {
        $Token = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($TokenB64))
        break
    }
    Start-Sleep -Seconds 1
}

if (-not $Token) {
    Write-Error "Token never populated -- is configs/rbac/service-account.yaml applied?"
    exit 1
}

$Lines = @(
    "apiVersion: v1"
    "kind: Config"
    "clusters:"
    "  - name: $ClusterName"
    "    cluster:"
    "      server: https://${ControlPlaneContainer}:6443"
    "      certificate-authority-data: $CaData"
    "contexts:"
    "  - name: incident-agent-context"
    "    context:"
    "      cluster: $ClusterName"
    "      namespace: $Namespace"
    "      user: incident-agent"
    "current-context: incident-agent-context"
    "users:"
    "  - name: incident-agent"
    "    user:"
    "      token: $Token"
)

New-Item -ItemType Directory -Force -Path (Split-Path $OutFile) | Out-Null
$Lines | Set-Content -Path $OutFile -Encoding utf8

Write-Host "Wrote $OutFile (server: https://${ControlPlaneContainer}:6443)"
