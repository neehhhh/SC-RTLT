param()

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$SourceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$LogFile = Join-Path $env:TEMP "Public_Real_Time_Checker-install.log"
$DesktopLog = Join-Path ([Environment]::GetFolderPath("Desktop")) "Public_Real_Time_Checker-install.log"
$InstallStage = "Initialisation"
$ReleaseDir = $null
$CurrentTmp = $null
$PreviousRelease = $null
$Activated = $false

function Write-Log {
    param([string]$Message)
    Add-Content -LiteralPath $LogFile -Value $Message -Encoding UTF8
}

function Test-CompatiblePython {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    & $Path -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
    return ($LASTEXITCODE -eq 0)
}

function Test-GraphicalRuntime {
    param([string]$Path)
    if (-not (Test-CompatiblePython -Path $Path)) {
        return $false
    }
    & $Path -c "import PySide6; from PySide6.QtWebEngineWidgets import QWebEngineView; from PySide6.QtMultimedia import QMediaPlayer" *> $null
    return ($LASTEXITCODE -eq 0)
}

function Find-CompatiblePython {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python314\python.exe"),
        (Join-Path $env:ProgramFiles "Python313\python.exe"),
        (Join-Path $env:ProgramFiles "Python312\python.exe"),
        (Join-Path $env:ProgramFiles "Python311\python.exe"),
        (Join-Path $env:ProgramFiles "Python314\python.exe")
    )

    foreach ($candidate in $candidates) {
        if (Test-CompatiblePython -Path $candidate) {
            return $candidate
        }
    }

    $py = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($null -ne $py) {
        foreach ($selector in @("-3.13", "-3.12", "-3.11", "-3.14")) {
            $resolved = (& $py.Source $selector -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1)
            $resolvedPath = ([string]$resolved).Trim()
            if ($LASTEXITCODE -eq 0 -and (Test-CompatiblePython -Path $resolvedPath)) {
                return $resolvedPath
            }
        }
    }

    $python = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($null -ne $python -and -not $python.Source.StartsWith((Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"), [System.StringComparison]::OrdinalIgnoreCase)) {
        if (Test-CompatiblePython -Path $python.Source) {
            return $python.Source
        }
    }

    return $null
}

function Show-Failure {
    param([System.Management.Automation.ErrorRecord]$ErrorRecord)

    try {
        Write-Log "ECHEC DE L'INSTALLATION"
        Write-Log ("Etape en echec : {0}" -f $InstallStage)
        Write-Log ("Erreur : {0}" -f $ErrorRecord.Exception.Message)
    }
    catch {}

    if (-not $Activated -and $ReleaseDir -and (Test-Path -LiteralPath $ReleaseDir)) {
        try { Remove-Item -LiteralPath $ReleaseDir -Recurse -Force -ErrorAction Stop } catch {}
    }
    if ($CurrentTmp -and (Test-Path -LiteralPath $CurrentTmp)) {
        try { Remove-Item -LiteralPath $CurrentTmp -Force -ErrorAction Stop } catch {}
    }

    try { Copy-Item -LiteralPath $LogFile -Destination $DesktopLog -Force } catch {}

    Write-Host ""
    Write-Host "============================================================"
    Write-Host "ECHEC DE L'INSTALLATION"
    Write-Host "============================================================"
    Write-Host ("Etape : {0}" -f $InstallStage)
    Write-Host "La version precedente reste intacte."
    Write-Host ("Journal : {0}" -f $LogFile)
    Write-Host ("Copie du journal : {0}" -f $DesktopLog)
    Write-Host ""
    Write-Host "Dernieres lignes du journal :"
    Write-Host "------------------------------------------------------------"
    if (Test-Path -LiteralPath $LogFile) {
        Get-Content -LiteralPath $LogFile -Tail 40
    }
    Write-Host "------------------------------------------------------------"
    Write-Host ""
    [void](Read-Host "Appuie sur Entree pour fermer cette fenetre")
}

try {
    Clear-Host
    Write-Host "============================================================"
    Write-Host "     PUBLIC REAL TIME CHECKER - INSTALLATEUR WINDOWS 11"
    Write-Host "============================================================"
    Write-Host ""
    Write-Host "L'installateur a bien demarre."
    Write-Host "Cette fenetre restera ouverte si une erreur se produit."
    Write-Host ""

    Set-Content -LiteralPath $LogFile -Value ("Demarrage de l'installation - {0}" -f (Get-Date -Format "dd/MM/yyyy HH:mm:ss")) -Encoding UTF8
    Write-Log ("Source : {0}" -f $SourceRoot)

    $VersionFile = Join-Path $SourceRoot "VERSION.txt"
    if (-not (Test-Path -LiteralPath $VersionFile -PathType Leaf)) {
        throw "VERSION.txt absent. Extrais completement le ZIP avant de lancer Setup.bat."
    }
    $AppVersion = (Get-Content -LiteralPath $VersionFile -Raw).Trim()
    if ([string]::IsNullOrWhiteSpace($AppVersion)) {
        throw "VERSION.txt est vide."
    }

    $AppRoot = Join-Path $env:LOCALAPPDATA "PublicRealTimeChecker"
    $ReleasesDir = Join-Path $AppRoot "releases"
    $DataDir = Join-Path $env:LOCALAPPDATA "PublicRealTimeCheckerData"
    $ConfigDir = Join-Path $env:APPDATA "PublicRealTimeChecker"
    $ReleaseId = "{0}-{1}" -f $AppVersion, ([Guid]::NewGuid().ToString("N").Substring(0, 12))
    $ReleaseDir = Join-Path $ReleasesDir $ReleaseId
    $CurrentFile = Join-Path $AppRoot "current.txt"
    $CurrentTmp = Join-Path $AppRoot "current.new"
    $AppWheel = Join-Path $SourceRoot ("packages\sc_rtlt-{0}-py3-none-any.whl" -f $AppVersion)
    $VerifyRuntime = Join-Path $SourceRoot "tools\verify_runtime.py"
    $StopScript = Join-Path $SourceRoot "tools\windows\stop_running_app.ps1"
    $ShortcutScript = Join-Path $SourceRoot "tools\windows\create_shortcuts.ps1"
    $CleanScript = Join-Path $SourceRoot "tools\windows\clean_old_releases.ps1"

    Write-Log ("Version : {0}" -f $AppVersion)
    Write-Log ("Programme : {0}" -f $AppRoot)
    Write-Log ("Nouvelle version : {0}" -f $ReleaseDir)

    foreach ($required in @(
        $AppWheel,
        $VerifyRuntime,
        (Join-Path $SourceRoot "Public_Real_Time_Checker.ico"),
        $StopScript,
        $ShortcutScript,
        $CleanScript,
        (Join-Path $SourceRoot "tools\windows\launcher.cmd"),
        (Join-Path $SourceRoot "tools\windows\launcher.vbs")
    )) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw ("Fichier d'installation manquant : {0}" -f $required)
        }
    }

    $PreviousPython = $null
    $RuntimeSourceRoot = $null
    foreach ($candidateRoot in @($AppRoot, (Join-Path $env:LOCALAPPDATA "SCWebCompanion"))) {
        $candidateCurrent = Join-Path $candidateRoot "current.txt"
        if (-not (Test-Path -LiteralPath $candidateCurrent -PathType Leaf)) {
            continue
        }
        $candidateRelease = (Get-Content -LiteralPath $candidateCurrent -Raw).Trim()
        if ([string]::IsNullOrWhiteSpace($candidateRelease)) {
            continue
        }
        $candidatePython = Join-Path $candidateRelease ".venv\Scripts\python.exe"
        if (Test-GraphicalRuntime -Path $candidatePython) {
            $PreviousRelease = $candidateRelease
            $PreviousPython = $candidatePython
            $RuntimeSourceRoot = $candidateRoot
            break
        }
    }

    $InstallStage = "Recherche du moteur Python"
    Write-Host "[1/7] Recherche du moteur Python..."
    $BasePython = $null
    if ($PreviousPython) {
        Write-Host "Runtime graphique de la version precedente detecte."
        Write-Log ("Runtime reutilisable : {0} (source {1})" -f (Join-Path $PreviousRelease ".venv"), $RuntimeSourceRoot)
    }
    else {
        $BasePython = Find-CompatiblePython
        if (-not $BasePython) {
            $winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue
            if ($null -eq $winget) {
                throw "Python 3.11 ou plus recent est absent et winget n'est pas disponible."
            }
            Write-Host ""
            Write-Host "Python compatible absent. Installation de Python 3.12 avec winget..."
            Write-Host "Cette etape peut afficher une demande Windows."
            Write-Log "Installation de Python 3.12 avec winget"
            & $winget.Source install --exact --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements *>> $LogFile
            if ($LASTEXITCODE -ne 0) {
                throw "winget n'a pas pu installer Python 3.12."
            }
            $BasePython = Find-CompatiblePython
        }
        if (-not $BasePython) {
            throw "Python 3.11 ou plus recent n'a pas pu etre trouve."
        }
        Write-Log ("Python utilise : {0}" -f $BasePython)
    }

    $InstallStage = "Fermeture de l'ancienne instance"
    Write-Host "[2/7] Fermeture de l'ancienne instance..."
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $StopScript -AppRoot $AppRoot *>> $LogFile
    Start-Sleep -Seconds 1

    $InstallStage = "Preparation de la nouvelle version"
    Write-Host ("[3/7] Preparation de la nouvelle version {0}..." -f $AppVersion)
    foreach ($directory in @($AppRoot, $ReleasesDir, $DataDir, $ConfigDir, $ReleaseDir)) {
        if (-not (Test-Path -LiteralPath $directory)) {
            New-Item -ItemType Directory -Path $directory -Force | Out-Null
        }
    }

    $InstallStage = "Preparation de l'environnement Python"
    Write-Host "[4/7] Preparation de l'environnement Python isole..."
    $RuntimeReused = $false
    $VenvDir = Join-Path $ReleaseDir ".venv"
    $InstalledPython = Join-Path $VenvDir "Scripts\python.exe"

    if ($PreviousPython) {
        Write-Log ("Copie locale du runtime precedent depuis {0}" -f (Join-Path $PreviousRelease ".venv"))
        & robocopy.exe (Join-Path $PreviousRelease ".venv") $VenvDir /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS /NP *>> $LogFile
        $RobocopyCode = $LASTEXITCODE
        if ($RobocopyCode -lt 8 -and (Test-GraphicalRuntime -Path $InstalledPython)) {
            $RuntimeReused = $true
            Write-Log "Runtime precedent copie et valide."
        }
        else {
            Write-Log ("Copie du runtime precedent inutilisable. Code robocopy : {0}. Creation d'un environnement neuf." -f $RobocopyCode)
            if (Test-Path -LiteralPath $VenvDir) {
                Remove-Item -LiteralPath $VenvDir -Recurse -Force
            }
            $BasePython = Find-CompatiblePython
        }
    }

    if (-not $RuntimeReused) {
        if (-not $BasePython) {
            $BasePython = Find-CompatiblePython
        }
        if (-not $BasePython) {
            throw "Aucun Python compatible n'est disponible pour creer l'environnement."
        }
        & $BasePython -m venv $VenvDir *>> $LogFile
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $InstalledPython -PathType Leaf)) {
            throw "La creation de l'environnement Python a echoue."
        }
        & $InstalledPython -m pip --version *>> $LogFile
        if ($LASTEXITCODE -ne 0) {
            throw "pip n'est pas disponible dans le nouvel environnement."
        }
    }

    $InstallStage = "Installation du paquet"
    Write-Host "[5/7] Installation de Public Real Time Checker..."

    # Une copie de runtime peut contenir une ancienne distribution. On vérifie
    # d'abord les métadonnées installées afin de ne jamais appeler pip uninstall
    # sur un paquet absent : sous Windows PowerShell 5.1, l'avertissement écrit
    # sur stderr pouvait être transformé en erreur fatale par ErrorActionPreference.
    $InstalledDistributionNames = @(
        & $InstalledPython -c "from importlib.metadata import distributions; print('\n'.join(sorted({(d.metadata.get('Name') or '').strip().lower().replace('_', '-') for d in distributions()})))"
    )
    if ($LASTEXITCODE -ne 0) {
        throw "La liste des paquets du runtime n'a pas pu etre lue."
    }

    foreach ($PackageToRemove in @("sc-web-companion", "sc-rtlt")) {
        if ($InstalledDistributionNames -contains $PackageToRemove) {
            Write-Log ("Suppression de l'ancien paquet : {0}" -f $PackageToRemove)
            $PreviousErrorActionPreference = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            try {
                & $InstalledPython -m pip uninstall -y $PackageToRemove *>> $LogFile
                $UninstallExitCode = $LASTEXITCODE
            }
            finally {
                $ErrorActionPreference = $PreviousErrorActionPreference
            }
            if ($UninstallExitCode -ne 0) {
                throw ("La suppression de l'ancien paquet {0} a echoue." -f $PackageToRemove)
            }
        }
        else {
            Write-Log ("Ancien paquet absent, aucune suppression necessaire : {0}" -f $PackageToRemove)
        }
    }

    if ($RuntimeReused) {
        Write-Host "Mise a jour locale : aucun nouveau telechargement graphique necessaire."
        & $InstalledPython -m pip install --disable-pip-version-check --no-index --no-deps --force-reinstall $AppWheel *>> $LogFile
    }
    else {
        Write-Host "Une connexion Internet est necessaire si les composants graphiques ne sont pas deja en cache."
        & $InstalledPython -m pip install --disable-pip-version-check --prefer-binary --retries 3 --timeout 180 $AppWheel *>> $LogFile
    }
    if ($LASTEXITCODE -ne 0) {
        throw "L'installation du paquet Public Real Time Checker a echoue."
    }

    $InstallStage = "Validation du runtime installe"
    Write-Host "[6/7] Validation de l'installation..."

    # Qt et FFmpeg peuvent écrire des messages d'information sur stderr tout en
    # terminant avec le code 0. Windows PowerShell 5.1 peut transformer ce flux
    # en erreur lorsque ErrorActionPreference vaut Stop. Start-Process isole les
    # deux flux : seule la valeur ExitCode décide si la validation a échoué.
    $ValidationToken = [Guid]::NewGuid().ToString("N")
    $ValidationStdout = Join-Path $env:TEMP ("Public_Real_Time_Checker-verify-{0}.out" -f $ValidationToken)
    $ValidationStderr = Join-Path $env:TEMP ("Public_Real_Time_Checker-verify-{0}.err" -f $ValidationToken)
    try {
        $ValidationArguments = @(
            ('"{0}"' -f $VerifyRuntime),
            ('"{0}"' -f $AppVersion)
        )
        $ValidationProcess = Start-Process `
            -FilePath $InstalledPython `
            -ArgumentList $ValidationArguments `
            -WorkingDirectory $ReleaseDir `
            -NoNewWindow `
            -Wait `
            -PassThru `
            -RedirectStandardOutput $ValidationStdout `
            -RedirectStandardError $ValidationStderr

        if (Test-Path -LiteralPath $ValidationStdout -PathType Leaf) {
            Get-Content -LiteralPath $ValidationStdout | Add-Content -LiteralPath $LogFile -Encoding UTF8
        }
        if (Test-Path -LiteralPath $ValidationStderr -PathType Leaf) {
            Get-Content -LiteralPath $ValidationStderr | Add-Content -LiteralPath $LogFile -Encoding UTF8
        }
        if ($ValidationProcess.ExitCode -ne 0) {
            throw ("Le test de demarrage et de fonctionnement a echoue avec le code {0}." -f $ValidationProcess.ExitCode)
        }
    }
    finally {
        Remove-Item -LiteralPath $ValidationStdout -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $ValidationStderr -Force -ErrorAction SilentlyContinue
    }
    Set-Content -LiteralPath (Join-Path $ReleaseDir "version.txt") -Value $AppVersion -Encoding ASCII

    Copy-Item -LiteralPath (Join-Path $SourceRoot "tools\windows\launcher.cmd") -Destination (Join-Path $AppRoot "Public_Real_Time_Checker.cmd") -Force
    Copy-Item -LiteralPath (Join-Path $SourceRoot "tools\windows\launcher.vbs") -Destination (Join-Path $AppRoot "Public_Real_Time_Checker.vbs") -Force
    Copy-Item -LiteralPath (Join-Path $SourceRoot "Public_Real_Time_Checker.ico") -Destination (Join-Path $AppRoot "Public_Real_Time_Checker.ico") -Force
    Copy-Item -LiteralPath $StopScript -Destination (Join-Path $AppRoot "stop_running_app.ps1") -Force
    Copy-Item -LiteralPath (Join-Path $SourceRoot "tools\windows\diagnostic.cmd") -Destination (Join-Path $AppRoot "DIAGNOSTIC.cmd") -Force
    Copy-Item -LiteralPath (Join-Path $SourceRoot "tools\windows\reset_data.cmd") -Destination (Join-Path $AppRoot "REINITIALISER_DONNEES.cmd") -Force
    Copy-Item -LiteralPath (Join-Path $SourceRoot "tools\windows\uninstall.cmd") -Destination (Join-Path $AppRoot "DESINSTALLER.cmd") -Force

    & $ShortcutScript -AppRoot $AppRoot -ReleaseDir $ReleaseDir *>> $LogFile
    if (-not $?) {
        throw "La creation des raccourcis a echoue."
    }

    Set-Content -LiteralPath $CurrentTmp -Value $ReleaseDir -Encoding ASCII
    Move-Item -LiteralPath $CurrentTmp -Destination $CurrentFile -Force
    Set-Content -LiteralPath (Join-Path $AppRoot "installed-version.txt") -Value $AppVersion -Encoding ASCII
    $Activated = $true

    $InstallStage = "Nettoyage des anciennes versions"
    Write-Host "[7/7] Nettoyage prudent des anciennes versions..."
    try {
        & $CleanScript -AppRoot $AppRoot -KeepRelease $ReleaseDir *>> $LogFile
    }
    catch {
        Write-Log ("Nettoyage non bloquant : {0}" -f $_.Exception.Message)
    }

    Write-Log "Installation terminee avec succes"
    Write-Host ""
    Write-Host "============================================================"
    Write-Host "INSTALLATION PUBLIC REAL TIME CHECKER TERMINEE AVEC SUCCES"
    Write-Host "============================================================"
    Write-Host "Le raccourci Public Real Time Checker a ete cree sur le Bureau."
    Write-Host ("Journal : {0}" -f $LogFile)
    Write-Host ""
    [void](Read-Host "Appuie sur Entree pour lancer l'application")
    Start-Process -FilePath (Join-Path $env:SystemRoot "System32\wscript.exe") -ArgumentList ('"{0}"' -f (Join-Path $AppRoot "Public_Real_Time_Checker.vbs"))
    exit 0
}
catch {
    Show-Failure -ErrorRecord $_
    exit 1
}
