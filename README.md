# SC-RTLT

SC-RTLT est un outil communautaire non officiel pour Star Citizen. Cette
version publique, **Public Real Time Checker 1.3.2**, réunit une application
Windows et un widget en surimpression pour suivre le lieu du joueur, afficher
l'heure locale du Verse et écouter des radios communautaires.

Le projet n'est ni développé, ni approuvé, ni soutenu par Cloud Imperium Games
ou Roberts Space Industries.

## Télécharger la version Windows

[Télécharger Public Real Time Checker 1.3.2 pour Windows 11](release/Public_Real_Time_Checker_1.3.2_Windows.zip)

Vérification SHA-256 :

```text
5888bcfd6ef964b5afd5a431e5b2c935a5dd6fe09c30c32952b05708925a370b
```

## Installation

1. Téléchargez puis extrayez entièrement le ZIP.
2. Ouvrez le dossier `Public_Real_Time_Checker_1.3.2_Windows`.
3. Double-cliquez sur `Setup.bat`.
4. Utilisez `Launcher.vbs` pour relancer l'application.
5. En cas d'échec, consultez `Public_Real_Time_Checker-install.log` sur le
   Bureau.

Windows peut afficher un avertissement SmartScreen, car l'application n'est
pas signée avec un certificat commercial.

## Fonctionnement

- Lecture locale et en lecture seule du fichier `Game.log`.
- Affichage de la localisation détectée dans un HUD déplaçable.
- Heure locale des planètes et lunes à partir des données VerseTime.
- Radios communautaires et affichage des métadonnées disponibles.
- Éditeur de disposition du HUD et personnalisation des couleurs.
- Bouton Wi-Fi pour associer manuellement un nom de lieu à un code technique.

Le bouton Wi-Fi écrit uniquement après validation du joueur. Aucun `Game.log`
complet n'est enregistré ou envoyé automatiquement.

Le fichier partageable produit par l'outil se trouve ici :

```text
%LOCALAPPDATA%\PublicRealTimeCheckerData\registry\Public_Real_Time_Checker_Registry.json
```

Consultez [PRIVACY.md](PRIVACY.md) pour le détail.

## Lancer depuis les sources

Prérequis : Windows 11 et Python 3.11 ou plus récent.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m sc_web_companion
```

Le nom `sc_web_companion` est conservé temporairement comme nom technique du
paquet Python pour assurer la compatibilité avec les installations existantes.

## Structure

- `src/sc_web_companion` : code source de l'application et du widget.
- `installer` : scripts de l'installateur Windows.
- `tools` : vérification du runtime installé.
- `release` : archive Windows prête à télécharger.

## Données tierces

Les données de temps et de lieux VerseTime conservent leur notice dans
`src/sc_web_companion/assets/versetime/NOTICE.txt`.

Star Citizen, Roberts Space Industries et leurs marques associées appartiennent
à leurs détenteurs respectifs.

## Licence

Le code de ce dépôt est publié sous
[GNU General Public License v3.0](LICENSE). La notice simplifiée incluse dans
le ZIP 1.3.2 est une notice historique de garantie et de marques ; la licence
applicable au code publié ici reste la GPL v3.
