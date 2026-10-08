# Builds configs/rbac/agent-kubeconfig.yaml bound to the incident-agent
# ServiceAccount -- this is the ONLY credential the agent process ever sees.
# Windows/PowerShell equivalent of infra/generate-agent-kubeconfig.sh
$ErrorActionPreference = "Stop"

$ClusterName = "kind-incident-agent-dev"
$Namespace   = "default"
$SecretName  = "incident-agent-token"
$OutFile     = "configs/rbac/agent-kubeconfig.yaml"

$Server = kubectl config view --raw -o "jsonpath={.clusters[?(@.name=='$ClusterName')].cluster.server}"
$CaData = kubectl config view --raw -o "jsonpath={.clusters[?(@.name=='$ClusterName')].cluster.certificate-authority-data}"

if (-not $Server -or -not $CaData) {
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
    Write-Error "Token never populated -- is configs/rbac/service-account.yaml applied? Run: kubectl apply -f configs/rbac/service-account.yaml"
    exit 1
}

$Lines = @(
    "apiVersion: v1"
    "kind: Config"
    "clusters:"
    "  - name: $ClusterName"
    "    cluster:"
    "      server: $Server"
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

Write-Host "Wrote $OutFile"