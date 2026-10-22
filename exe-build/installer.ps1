param(
    [string]$ParentPath,
    [string]$DesktopPath,
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
$appName = 'Tokens用量统计中文看板'
$exeName = 'Tokens用量统计中文看板.exe'
$sourceExe = Join-Path $PSScriptRoot 'app.exe'
$interactive = -not $ParentPath

function Show-InstallerMessage([string]$Message, [string]$Title, [string]$Kind = 'Information') {
    Add-Type -AssemblyName System.Windows.Forms
    $icon = [System.Windows.Forms.MessageBoxIcon]::$Kind
    [void][System.Windows.Forms.MessageBox]::Show(
        $Message, $Title,
        [System.Windows.Forms.MessageBoxButtons]::OK,
        $icon
    )
}

try {
    if (-not (Test-Path -LiteralPath $sourceExe -PathType Leaf)) {
        throw '安装包内容不完整，找不到主程序。请重新下载完整安装包。'
    }

    if ($interactive) {
        Add-Type -AssemblyName System.Windows.Forms
        $defaultParent = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs'
        New-Item -ItemType Directory -Path $defaultParent -Force | Out-Null
        $picker = New-Object System.Windows.Forms.FolderBrowserDialog
        $picker.Description = '请选择安装父目录，安装程序会在其中创建软件文件夹。'
        $picker.SelectedPath = $defaultParent
        $picker.ShowNewFolderButton = $true
        if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
        $ParentPath = $picker.SelectedPath
    }

    $parent = (Resolve-Path -LiteralPath $ParentPath).Path
    $installDir = Join-Path $parent $appName
    $installedExe = Join-Path $installDir $exeName
    if ((Test-Path -LiteralPath $installedExe -PathType Leaf) -and $interactive) {
        $updatePrompt = '检测到已安装版本。更新程序文件并保留本地数据吗？' + [Environment]::NewLine + [Environment]::NewLine + $installDir
        $answer = [System.Windows.Forms.MessageBox]::Show(
            $updatePrompt, $appName,
            [System.Windows.Forms.MessageBoxButtons]::YesNo,
            [System.Windows.Forms.MessageBoxIcon]::Question
        )
        if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) { exit 0 }
    }

    New-Item -ItemType Directory -Path $installDir -Force | Out-Null
    $stagedExe = Join-Path $installDir ('.' + $exeName + '.new')
    try {
        Copy-Item -LiteralPath $sourceExe -Destination $stagedExe -Force
        Move-Item -LiteralPath $stagedExe -Destination $installedExe -Force
    } finally {
        if (Test-Path -LiteralPath $stagedExe) {
            Remove-Item -LiteralPath $stagedExe -Force
        }
    }

    if (-not $DesktopPath) {
        $DesktopPath = [Environment]::GetFolderPath('DesktopDirectory')
    }
    New-Item -ItemType Directory -Path $DesktopPath -Force | Out-Null
    $shortcutPath = Join-Path $DesktopPath ($appName + '.lnk')
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $installedExe
    $shortcut.WorkingDirectory = $installDir
    $shortcut.IconLocation = "$installedExe,0"
    $shortcut.Description = $appName
    $shortcut.Save()

    if ($interactive) {
        $completeMessage = '安装完成。' + [Environment]::NewLine + [Environment]::NewLine +
            '程序文件夹：' + [Environment]::NewLine + $installDir + [Environment]::NewLine + [Environment]::NewLine +
            '桌面快捷方式已创建。现在启动软件吗？'
        $answer = [System.Windows.Forms.MessageBox]::Show(
            $completeMessage, $appName,
            [System.Windows.Forms.MessageBoxButtons]::YesNo,
            [System.Windows.Forms.MessageBoxIcon]::Information
        )
        if ($answer -eq [System.Windows.Forms.DialogResult]::Yes -and -not $NoLaunch) {
            Start-Process -FilePath $installedExe -WorkingDirectory $installDir
        }
    }
} catch {
    if ($interactive) {
        Show-InstallerMessage ("安装失败：" + [Environment]::NewLine + $_.Exception.Message) $appName 'Error'
    }
    exit 1
}
