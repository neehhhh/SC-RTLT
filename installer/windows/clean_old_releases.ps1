param(
    [Parameter(Mandatory = $true)]
    [string]$AppRoot,
    [Parameter(Mandatory = $true)]
    [string]$KeepRelease
)

$ErrorActionPreference = "SilentlyContinue"
$releasesDir = Join-Path $AppRoot "releases"
$keepFull = [System.IO.Path]::GetFullPath($KeepRelease).TrimEnd([char]92)

if (Test-Path $releasesDir) {
    foreach ($directory in (Get-ChildItem -Path $releasesDir -Directory -ErrorAction SilentlyContinue)) {
        $full = [System.IO.Path]::GetFullPath($directory.FullName).TrimEnd([char]92)
        if (-not $full.Equals($keepFull, [System.StringComparison]::OrdinalIgnoreCase)) {
            try {
                Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction Stop
                Write-Output ("Ancienne version supprimee : {0}" -f $full)
            }
            catch {
                Write-Output ("Ancienne version conservee car encore verrouillee : {0}" -f $full)
            }
        }
    }
}

# Nettoyage prudent de l'ancien layout 0.8 installe directement dans APP_ROOT.
# Les fichiers verrouilles sont conserves et ne font jamais echouer la mise a jour.
$legacyNames = @(
    ".venv",
    "main.py",
    "requirements.txt",
    "assets",
    "sc_web_companion",
    "scripts",
    "tests"
)
foreach ($name in $legacyNames) {
    $legacyPath = Join-Path $AppRoot $name
    if (Test-Path -LiteralPath $legacyPath) {
        try {
            Remove-Item -LiteralPath $legacyPath -Recurse -Force -ErrorAction Stop
            Write-Output ("Ancien element du layout 0.8 supprime : {0}" -f $legacyPath)
        }
        catch {
            Write-Output ("Ancien element conserve car encore verrouille : {0}" -f $legacyPath)
        }
    }
}
exit 0
