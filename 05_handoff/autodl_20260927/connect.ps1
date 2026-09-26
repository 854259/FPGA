param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9.-]+$')][string]$Server,
    [Parameter(Mandatory=$true)][ValidateRange(1,65535)][int]$Port,
    [ValidateSet('Connect','Upload','Tunnel')][string]$Action='Connect'
)
$ErrorActionPreference='Stop'
if ($Action -eq 'Upload') {
    & scp -P $Port (Join-Path $PSScriptRoot 'autodl-rtl-kit.tar.gz') (Join-Path $PSScriptRoot 'autodl-rtl-kit.tar.gz.sha256') "root@${Server}:/root/autodl-tmp/"
} elseif ($Action -eq 'Tunnel') {
    & ssh -o ExitOnForwardFailure=yes -p $Port -N -L '127.0.0.1:18000:127.0.0.1:8000' -L '127.0.0.1:17860:127.0.0.1:7860' "root@$Server"
} else {
    & ssh -p $Port "root@$Server"
}
exit $LASTEXITCODE
