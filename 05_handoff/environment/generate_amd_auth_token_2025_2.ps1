$ErrorActionPreference = 'Stop'

$parent = 'F:\vivado\.xinstall\2025.2'
$native = "$parent\lib\win64.o"
$java = "$parent\tps\win64\jre21.0.5_11\bin\java.exe"
$classPath = (Get-ChildItem -LiteralPath "$parent\lib\classes" -Filter '*.jar' | ForEach-Object FullName) -join ';'
$env:Path = "$native;C:\Windows\System32;C:\Windows\System32\wbem;C:\Windows"
$logDir = Join-Path $env:USERPROFILE '.Xilinx\xinstall'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$log = Join-Path $logDir 'auth-token-2025.2.log'

$javaArgs = @(
    '-DLOAD_64_NATIVE=true'
    '-DOS_ARCH=64'
    "-Djava.library.path=$native"
    '-Dsun.java2d.d3d=false'
    "-DIDATA_LOCATION_FROM_USER=$parent\data\idata.dat"
    "-Duser.dir=$parent"
    "-Duser.home=$env:USERPROFILE"
    "-DDYNAMIC_LANGUAGE_BUNDLE=$parent\data"
    '-Dslf4j.internal.verbosity=ERROR'
    "-DINSTALLER_ROOT_DIR=$parent"
    "-Dlogback.configurationFile=$parent/data/logback.xml"
    '-DHAS_DYNAMIC_LANGUAGE_BUNDLE=true'
    "-DLOG_FILE=$log"
)

Write-Host 'Enter your AMD account credentials only in this window.'
Write-Host 'The password is not echoed. Do not send credentials in chat.'
& $java @javaArgs -cp $classPath com.xilinx.installer.api.InstallerLauncher -b AuthTokenGen
if ($LASTEXITCODE -ne 0) { throw "AuthTokenGen failed with exit code $LASTEXITCODE" }
Write-Host 'SUCCESS: AMD installer authentication token generated.'
