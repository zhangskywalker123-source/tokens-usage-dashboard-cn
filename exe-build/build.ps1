param(
    [string]$NodeExe
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$stageDir = Join-Path $PSScriptRoot 'stage'
$bundleDir = Join-Path $PSScriptRoot 'bundle'
$runtimeDir = Join-Path $bundleDir 'runtime'

if (-not $NodeExe) {
    if ($env:TOKEN_DASH_NODE_EXE) {
        $NodeExe = $env:TOKEN_DASH_NODE_EXE
    } elseif (Test-Path -LiteralPath (Join-Path $runtimeDir 'node.exe')) {
        $NodeExe = Join-Path $runtimeDir 'node.exe'
    } else {
        $NodeExe = (Get-Command node.exe -ErrorAction Stop).Source
    }
}

$NodeExe = (Resolve-Path -LiteralPath $NodeExe).Path
$nodeVersion = (& $NodeExe --version).Trim()
if ($nodeVersion -notmatch '^v22\.') {
    throw "Node.js 22 is required to prepare the packaged runtime; found $nodeVersion"
}

$nodeDir = Split-Path -Parent $NodeExe
$env:PATH = "$nodeDir;$env:PATH"
$npm = Join-Path $nodeDir 'npm.cmd'
if (-not (Test-Path -LiteralPath $npm)) {
    $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
}

Write-Host "Installing locked CodeBurn dependencies with $nodeVersion ..."
& $npm ci --prefix $stageDir
if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit code $LASTEXITCODE" }

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
$runtimeNode = Join-Path $runtimeDir 'node.exe'
if ([IO.Path]::GetFullPath($NodeExe) -ne [IO.Path]::GetFullPath($runtimeNode)) {
    Copy-Item -LiteralPath $NodeExe -Destination $runtimeNode -Force
}
Copy-Item -LiteralPath (Join-Path $stageDir 'node_modules') -Destination $runtimeDir -Recurse -Force
Copy-Item -LiteralPath (Join-Path $projectRoot 'build.js') -Destination (Join-Path $bundleDir 'build.js') -Force
Copy-Item -LiteralPath (Join-Path $projectRoot 'chart.umd.min.js') -Destination (Join-Path $bundleDir 'chart.umd.min.js') -Force

Push-Location $PSScriptRoot
try {
    Write-Host 'Running regression tests ...'
    Push-Location $projectRoot
    try {
        & $NodeExe --test (Join-Path $projectRoot 'tests\dashboard.test.js')
        if ($LASTEXITCODE -ne 0) { throw "Node tests failed with exit code $LASTEXITCODE" }
        python -m py_compile (Join-Path $PSScriptRoot 'native_dashboard.py')
        if ($LASTEXITCODE -ne 0) { throw "Native dashboard syntax check failed with exit code $LASTEXITCODE" }
        python -m unittest discover -s tests -p 'test_*.py' -v
        if ($LASTEXITCODE -ne 0) { throw "Python tests failed with exit code $LASTEXITCODE" }
    } finally {
        Pop-Location
    }

    Write-Host 'Building TokenDashCN.exe ...'
    python -m PyInstaller --noconfirm TokenDashCN.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

    Write-Host 'Building native Tokens用量统计中文看板.exe ...'
    python -m PyInstaller --noconfirm TokenDashGUI.spec
    if ($LASTEXITCODE -ne 0) { throw "Native PyInstaller build failed with exit code $LASTEXITCODE" }

    $nativeExe = Join-Path $PSScriptRoot 'dist\Tokens用量统计中文看板.exe'
    $archiveEntries = & python -m PyInstaller.utils.cliutils.archive_viewer -b -l $nativeExe 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the native EXE archive.' }
    if (-not ($archiveEntries | Where-Object { $_.Trim() -eq 'runtime.zip' })) {
        throw 'Native EXE verification failed: runtime.zip is not at the embedded extraction root.'
    }

    Write-Host 'Building standalone installer ...'
    $iexpress = Join-Path (Join-Path $env:WINDIR 'System32') 'iexpress.exe'
    if (-not (Test-Path -LiteralPath $iexpress)) { throw 'Windows IExpress was not found.' }
    $installerStage = Join-Path $PSScriptRoot 'installer-stage'
    New-Item -ItemType Directory -Path $installerStage -Force | Out-Null
    Copy-Item -LiteralPath $nativeExe -Destination (Join-Path $installerStage 'app.exe') -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'installer.ps1') -Destination (Join-Path $installerStage 'install.ps1') -Force

    $setupExe = Join-Path (Join-Path $PSScriptRoot 'dist') 'Tokens用量看板安装程序.exe'
    $sedTarget = Join-Path $installerStage 'setup.exe'
    $sedPath = Join-Path $installerStage 'setup.sed'
    $sed = @"
[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=1
UseLongFileName=1
InsideCompressed=1
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName=%TargetName%
FriendlyName=%FriendlyName%
AppLaunched=%AppLaunched%
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
SourceFiles=SourceFiles
[Strings]
TargetName=$sedTarget
FriendlyName=Tokens Usage Dashboard Setup
AppLaunched=powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1
SourceDir=$installerStage
FILE0=install.ps1
FILE1=app.exe
[SourceFiles]
SourceFiles0=%SourceDir%
[SourceFiles0]
%FILE0%=
%FILE1%=
"@
    [System.IO.File]::WriteAllText($sedPath, $sed, [System.Text.Encoding]::ASCII)
    if (Test-Path -LiteralPath $sedTarget) { Remove-Item -LiteralPath $sedTarget -Force }
    & $iexpress /N /Q $sedPath
    if ($LASTEXITCODE -ne 0) { throw "IExpress installer build failed with exit code $LASTEXITCODE" }
    $deadline = [DateTime]::UtcNow.AddMinutes(10)
    $previousLength = 0
    $stableChecks = 0
    while ($stableChecks -lt 3 -and [DateTime]::UtcNow -lt $deadline) {
        if (Test-Path -LiteralPath $sedTarget -PathType Leaf) {
            $currentLength = (Get-Item -LiteralPath $sedTarget).Length
            if ($currentLength -gt 0 -and $currentLength -eq $previousLength) {
                $stableChecks++
            } else {
                $stableChecks = 0
            }
            $previousLength = $currentLength
        }
        if ($stableChecks -lt 3) { Start-Sleep -Seconds 2 }
    }
    if ($stableChecks -lt 3) { throw 'IExpress did not finish creating a stable setup executable within 10 minutes.' }
    Copy-Item -LiteralPath $sedTarget -Destination $setupExe -Force
    Write-Host "Installer created: $setupExe"
} finally {
    Pop-Location
}
