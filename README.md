# SC-RTLT

SC-RTLT is an unofficial, community-made Star Citizen companion for Windows.
It combines an always-on-top overlay, location and Verse-time information,
community radio, and a curated web browser in one application.

> SC-RTLT is an unofficial Star Citizen fan project and is not affiliated with
> the Cloud Imperium group of companies. Third-party content remains the
> property of its respective owners.

## Features

- **14 independent fan-made radio streams:** five HCN Radio streams, The
  People's Radio, and eight REC·REG streams.
- **A single Star Citizen browser:** open a curated selection of community and
  official Star Citizen-related sites in persistent tabs, and add your own
  sites.
- **Designed for use while playing:** the movable, always-on-top widget and
  integrated controls remain available over the game. SC-RTLT does not inject
  code into or modify Star Citizen.
- **English and French:** switch the interface language from the application.
- **Local location detection:** read `Game.log` locally and display the detected
  location in the HUD.
- **Verse time and HUD customization:** show local planetary time and customize
  HUD layout and colors.
- **In-app updates:** use the yellow update button at the top of Settings to
  download a verified GitHub Release and restart the widget automatically.

Radio programming and linked websites are provided by independent third
parties. SC-RTLT does not host, produce, edit, moderate, or control their
content. See [LEGAL.md](LEGAL.md) and [PRIVACY.md](PRIVACY.md).

## Download

[Download SC-RTLT Public 1.3.5 for Windows](https://github.com/neehhhh/SC-RTLT/releases/latest/download/SC-RTLT_Public_1.3.5_Windows.zip)

SHA-256:

```text
561eee4ddcedb88c3219a5e791cd843d0419756c0230d7ae1244cb8ec07f6c45
```

Windows SmartScreen may display a warning because the application is not
signed with a commercial code-signing certificate.

## Installation

1. Download and fully extract the ZIP archive.
2. Open the `SC-RTLT_Public_1.3.5_Windows` folder.
3. Double-click `Setup.bat`.
4. Use `Launcher.vbs` to start the application again later.
5. If installation fails, review `SC-RTLT-Public-install.log` on the Desktop.

## Local data

SC-RTLT reads `Game.log` locally and in read-only mode. It never copies or
uploads the complete log. The Wi-Fi button writes a location record only after
the player confirms the action.

The optional, shareable registry file is stored at:

```text
%LOCALAPPDATA%\SCRTLTPublicData\registry\SC-RTLT_Public_Registry.json
```

The application does not upload this file automatically.

## Run from source

Requirements: Windows 11 and Python 3.11 or later.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m sc_web_companion
```

`sc_web_companion` remains the internal Python package name for compatibility
with existing installations.

## Repository layout

- `src/sc_web_companion`: application and widget source code.
- `installer`: Windows release-layout and installer sources.
- `release`: downloadable Windows archive, checksum, and release notes.
- `LEGAL.md`: third-party content and unofficial-project notices.
- `PRIVACY.md`: local data and network behavior.

## Third-party data

VerseTime data retains its attribution notice in
`src/sc_web_companion/assets/versetime/NOTICE.txt`.

The official Star Citizen website is
[Roberts Space Industries](https://robertsspaceindustries.com/).

## License

The source code in this repository is licensed under the
[GNU General Public License v3.0](LICENSE).
