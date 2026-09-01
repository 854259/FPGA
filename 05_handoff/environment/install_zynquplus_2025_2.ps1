#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$installer = 'F:\vivado\.xinstall\2025.2\bin\xsetup.bat'
$config = 'D:\HUST\IC\FPGA\05_handoff\environment\amd_2025.2_add_zynquplus_config.txt'
$verifyTcl = 'D:\HUST\IC\FPGA\05_handoff\environment\verify_xczu3eg_part.tcl'
$vivado = 'F:\vivado\2025.2\Vivado\bin\vivado.bat'
$resultLog = 'D:\HUST\IC\FPGA\05_handoff\environment\zynquplus_install_result.log'

if (-not (Test-Path -LiteralPath $installer)) { throw "Installer not found: $installer" }
if (-not (Test-Path -LiteralPath $config)) { throw "Config not found: $config" }

Write-Host 'AMD download authentication is required once.'
Write-Host 'Enter credentials only in this installer window; do not send them in chat.'
& $installer -b AuthTokenGen
if ($LASTEXITCODE -ne 0) { throw "AuthTokenGen failed with exit code $LASTEXITCODE" }

& $installer -a XilinxEULA,3rdPartyEULA -b Add -c $config
if ($LASTEXITCODE -ne 0) { throw "Incremental Add failed with exit code $LASTEXITCODE" }

$env:PROCESSOR_ARCHITECTURE = 'AMD64'
$env:XILINX_LOCAL_USER_DATA = 'no'
& $vivado -mode batch -nojournal -nolog -source $verifyTcl 2>&1 | Tee-Object -FilePath $resultLog
if ($LASTEXITCODE -ne 0) { throw "Vivado target-part verification failed with exit code $LASTEXITCODE" }

Write-Host "SUCCESS: xczu3eg-sbva484-1-e is installed. Evidence: $resultLog"
