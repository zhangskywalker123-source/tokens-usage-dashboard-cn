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
} finally {
    Pop-Location
}
