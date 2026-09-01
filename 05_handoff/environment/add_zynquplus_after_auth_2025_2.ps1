#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$installer = 'F:\vivado\.xinstall\2025.2\bin\xsetup.bat'
$config = 'D:\HUST\IC\FPGA\05_handoff\environment\amd_2025.2_add_zynquplus_config.txt'
$verifyTcl = 'D:\HUST\IC\FPGA\05_handoff\environment\verify_xczu3eg_part.tcl'
$vivado = 'F:\vivado\2025.2\Vivado\bin\vivado.bat'
$resultLog = 'D:\HUST\IC\FPGA\05_handoff\environment\zynquplus_install_result.log'

$maxAttempts = 4
$installExit = 1
for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
    Write-Host "AMD incremental install attempt $attempt of $maxAttempts"
    & $installer -a XilinxEULA,3rdPartyEULA -b Add -c $config
    $installExit = $LASTEXITCODE
    if ($installExit -eq 0) { break }
    if ($attempt -lt $maxAttempts) {
        Write-Warning "Download/install attempt failed with exit code $installExit; retrying in 20 seconds."
        Start-Sleep -Seconds 20
    }
}
if ($installExit -ne 0) { throw "Incremental Add failed after $maxAttempts attempts; last exit code $installExit" }

$env:PROCESSOR_ARCHITECTURE = 'AMD64'
$env:XILINX_LOCAL_USER_DATA = 'no'
& $vivado -mode batch -nojournal -nolog -source $verifyTcl 2>&1 | Tee-Object -FilePath $resultLog
if ($LASTEXITCODE -ne 0) { throw "Vivado target-part verification failed with exit code $LASTEXITCODE" }

Write-Host "SUCCESS: xczu3eg-sbva484-1-e is installed. Evidence: $resultLog"
