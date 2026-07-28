param(
    [Parameter(Mandatory = $true)][string]$AppRoot,
    [Parameter(Mandatory = $true)][string]$ReleaseDir
)
$ErrorActionPreference = "Stop"
$ws = New-Object -ComObject WScript.Shell
$launcher = Join-Path $AppRoot "Public_Real_Time_Checker.vbs"
$wscript = Join-Path $env:SystemRoot "System32\wscript.exe"
$pythonw = Join-Path $ReleaseDir ".venv\Scripts\pythonw.exe"
$appIcon = Join-Path $AppRoot "Public_Real_Time_Checker.ico"
$desktop = [Environment]::GetFolderPath("Desktop")
$programs = [Environment]::GetFolderPath("Programs")
foreach ($folder in @($desktop, $programs)) {
    $shortcutPath = Join-Path $folder "Public Real Time Checker.lnk"
    $shortcut = $ws.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $wscript
    $shortcut.Arguments = '"' + $launcher + '"'
    $shortcut.WorkingDirectory = $AppRoot
    $shortcut.IconLocation = if (Test-Path -LiteralPath $appIcon) { "$appIcon,0" } else { "$pythonw,0" }
    $shortcut.Description = "Public Real Time Checker pour Star Citizen"
    $shortcut.Save()
}
