param([switch]$IncludeLocalRuntime)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$vivadoBin = if ($env:VIVADO_BIN) { $env:VIVADO_BIN } else { 'F:\vivado\2026.1\Vivado\bin' }

Write-Host "PROJECT=$root"
Write-Host "VIVADO_BIN=$vivadoBin"
foreach ($name in 'vivado.bat', 'xvlog.bat', 'xelab.bat', 'xsim.bat') {
    $path = Join-Path $vivadoBin $name
    Write-Host "$name=$([bool](Test-Path -LiteralPath $path))"
}

$candidate = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
$pythonPath = if (Test-Path -LiteralPath $candidate) {
    $candidate
} else {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) { $pythonCommand.Source } else { $null }
}
if ($pythonPath) {
    & $pythonPath --version
} else {
    Write-Host 'PYTHON=NOT_FOUND'
}

$modelOk = $true
$dockerExit = 0
if ($IncludeLocalRuntime) {
    $modelPath = Join-Path $root 'model\qwen2.5-coder-7b-instruct-q4_k_m.gguf'
    $modelOk = Test-Path -LiteralPath $modelPath
    if ($modelOk) {
        $modelFile = Get-Item -LiteralPath $modelPath
        $modelHash = (Get-FileHash -LiteralPath $modelPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $modelOk = $modelFile.Length -eq 4683073536 -and $modelHash -eq '509287f78cb4d4cf6b3843734733b914b2c158e43e22a7f4bf5e963800894d3c'
        Write-Host "MODEL_BYTES=$($modelFile.Length) MODEL_SHA256=$modelHash MODEL_OK=$modelOk"
    } else {
        Write-Host 'MODEL=NOT_FOUND'
    }
} else {
    Write-Host 'LOCAL_MODEL_AND_DOCKER=NOT_REQUESTED (27B evaluation runs on the teammate machine)'
}

$env:PROCESSOR_ARCHITECTURE = if ($env:PROCESSOR_ARCHITECTURE) { $env:PROCESSOR_ARCHITECTURE } else { 'AMD64' }
$env:XILINX_LOCAL_USER_DATA = 'no'
& (Join-Path $vivadoBin 'vivado.bat') -mode batch -nolog -nojournal -notrace `
    -source (Join-Path $root 'tools\check_part.tcl')
$partExit = $LASTEXITCODE
Write-Host "TARGET_PART_EXIT=$partExit"

if ($IncludeLocalRuntime) {
    & wsl.exe -d Ubuntu-22.04-ROS2 -- bash -lc 'docker version --format "client={{.Client.Version}} server={{.Server.Version}}" && docker image inspect amd-rtl-local/ubuntu:22.04 --format "base={{.Os}}/{{.Architecture}} bytes={{.Size}}" && docker image inspect amd-rtl-agent:dev --format "agent={{.Os}}/{{.Architecture}} bytes={{.Size}}" && docker run --rm --network none --entrypoint llama-server amd-rtl-agent:dev --version'
    $dockerExit = $LASTEXITCODE
    Write-Host "DOCKER_EXIT=$dockerExit"
}

if (-not $pythonPath -or -not $modelOk -or $partExit -ne 0 -or $dockerExit -ne 0) { exit 1 }
Write-Host 'ENVIRONMENT_CHECK=PASS'
Write-Host "INCLUDE_LOCAL_RUNTIME=$IncludeLocalRuntime"
