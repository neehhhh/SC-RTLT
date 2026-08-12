param(
    [Parameter(Mandatory = $true)]
    [string]$AppRoot
)

$ErrorActionPreference = "SilentlyContinue"
$normalizedRoot = [System.IO.Path]::GetFullPath($AppRoot).TrimEnd([char]92)

function Get-ScwcProcesses {
    $matches = @()
    foreach ($process in (Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {
        if ($process.ProcessId -eq $PID) {
            continue
        }
        $commandLine = [string]$process.CommandLine
        $executable = [string]$process.ExecutablePath
        $commandMatch = $false
        $executableMatch = $false

        if ($commandLine) {
            $commandMatch = $commandLine.IndexOf($normalizedRoot, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
        }
        if ($executable) {
            $executableMatch = $executable.StartsWith($normalizedRoot, [System.StringComparison]::OrdinalIgnoreCase)
        }

        if ($commandMatch -or $executableMatch) {
            $matches += $process
        }
    }
    return $matches
}

$targets = Get-ScwcProcesses
foreach ($process in $targets) {
    try {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        Write-Output ("Processus arrete : {0} PID={1}" -f $process.Name, $process.ProcessId)
    }
    catch {
        Write-Output ("Impossible d'arreter PID={0} : {1}" -f $process.ProcessId, $_.Exception.Message)
    }
}

for ($attempt = 0; $attempt -lt 30; $attempt++) {
    $remaining = Get-ScwcProcesses
    if ($remaining.Count -eq 0) {
        exit 0
    }
    Start-Sleep -Milliseconds 200
}

$remaining = Get-ScwcProcesses
if ($remaining.Count -gt 0) {
    Write-Output "Certains anciens processus sont encore actifs. L'installation versionnee continuera sans supprimer leurs fichiers."
}
exit 0
