param([switch]$Benchmark20)

$ErrorActionPreference = 'Stop'
if ($Benchmark20) {
    $datasetPath = Join-Path $PSScriptRoot 'bench\verilog-eval\dataset_spec-to-rtl'
    $promptFiles = @(Get-ChildItem -LiteralPath $datasetPath -Filter '*_prompt.txt' -Recurse | Sort-Object FullName | Select-Object -First 20)
    if ($promptFiles.Count -ne 20) { throw 'Expected 20 benchmark problems.' }
    foreach ($promptFile in $promptFiles) {
        foreach ($suffix in '_ref.sv', '_test.sv') {
            $companion = $promptFile.FullName -replace '_prompt\.txt$', $suffix
            if (-not (Test-Path -LiteralPath $companion)) { throw "Missing dataset file: $companion" }
        }
    }
}
if (-not $env:LLM_API_KEY) {
    $env:LLM_API_KEY = [Environment]::GetEnvironmentVariable('LLM_API_KEY', 'User')
}
if (-not $env:LLM_API_KEY) {
    $secureKey = Read-Host 'Enter API key (hidden input)' -AsSecureString
    $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    try {
        $env:LLM_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
        $secureKey.Dispose()
    }
    if ([string]::IsNullOrWhiteSpace($env:LLM_API_KEY)) { throw 'API key cannot be empty.' }
}
$env:LLM_BASE_URL = 'https://ws-zx533vazjgfeshi6.cn-beijing.maas.aliyuncs.com/compatible-mode/v1'
$env:LLM_MODEL = 'qwen3.6-27b'
$env:LLM_ENABLE_THINKING = 'false'
$env:LLM_MAX_TOKENS = '2048'
$env:LLM_TIMEOUT_SECONDS = '120'
$env:VIVADO_BIN = 'E:\vivado\2025.2\Vivado\bin'
Remove-Item Env:LLM_MOCK_FILE -ErrorAction SilentlyContinue
$runPrefix = if ($Benchmark20) { 'outputs\cloud_benchmark20_' } else { 'outputs\cloud_smoke_' }
$runDir = Join-Path $PSScriptRoot ($runPrefix + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $runDir | Out-Null
Push-Location $PSScriptRoot
try {
    Write-Host "Results: $runDir"
    if ($Benchmark20) {
        Write-Host 'Running 20 VerilogEval problems: Qwen3.6-27B, baseline + one agent candidate, at most one repair, full Vivado checks.'
        & python .\agent.py benchmark --dataset $datasetPath --output-dir $runDir --limit 20 --samples 1 --repairs 1
    } else {
        Write-Host 'Running Qwen3.6-27B + Vivado: baseline, one candidate, at most one repair.'
        & python .\agent.py run --problem .\tests\fixtures\problem.txt --output-dir $runDir --testbench .\tests\fixtures\test.sv --reference .\tests\fixtures\ref.sv --samples 1 --repairs 1
    }
    $runExit = $LASTEXITCODE
    Set-Content -LiteralPath (Join-Path $runDir 'process_exit_code.txt') -Value $runExit
    Write-Host "Results: $runDir"
    if ($runExit -ne 0) { throw "Cloud smoke failed: $runExit" }
    if ($Benchmark20) {
        $summary = Get-Content -LiteralPath (Join-Path $runDir 'benchmark.json') -Raw | ConvertFrom-Json
        $baselinePassed = @($summary.records | Where-Object { $_.baseline_pass -eq $true }).Count
        $agentPassed = @($summary.records | Where-Object { $_.pass_at_1 -eq $true }).Count
        Write-Host "Complete=$($summary.complete); baseline=$baselinePassed/20; agent=$agentPassed/20"
    }
} finally { Pop-Location }
