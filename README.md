# SC-RTLT

<img width="1891" height="143" alt="image (1)" src="https://github.com/user-attachments/assets/615f5f84-a169-4a3a-9deb-ea3f7662a440" />

SC-RTLT is an unofficial, community-made Star Citizen companion for Windows.
It is an overlay with location and Verse-time information,
community radios and a web browser.

> SC-RTLT is an unofficial Star Citizen fan project and is not affiliated with
> the Cloud Imperium group of companies or the radios streamed in this app.
> Third-party content remains the property of its respective owners and creators.

## Features

<img width="1920" height="1080" alt="mainui" src="https://github.com/user-attachments/assets/7c8e8f59-0c17-401d-a26a-4d27f37431e7" />


<img width="1917" height="1078" alt="Settingshud" src="https://github.com/user-attachments/assets/24ae9805-1aa7-4ebd-b92a-22e6389df541" />

- 14 independent fan-made radio streams
- Single Star Citizen browser
- Verse time and HUD customization
- English and French
- Alpha : Group and Raid UI

Radio programming and linked websites are provided by independent third
parties. SC-RTLT does not host, produce, edit, moderate, or control their
content. See [LEGAL.md](LEGAL.md) and [PRIVACY.md](PRIVACY.md).

> ## Raid and Group UI :
>
> The widget gets the name with the invite notification and go fetch some basics information from players RSI profil page. Name, Org logo and name, Title. If the group goes up to +5 it switch to the Raid UI to compact the widget and stay at the same size.
>
> Disabled by default, you can enable it in the settings.
> SC-RTLT now use a CloudFlare so if everybody in the group use the widget, they get more stables information. Only the player ID, in-game location and vehicules channels is shared and encrypted before reaching cloudflare.

> Features :
Group UI up to 4 players
Raid UI up to 12 players

To be RGPD compliant, you need to accept access to CloudFlare in the settings.

This is still a bit experimental, depending on situation, server confidtions the rights notification doesn't show up and doesn't notify the widget. 
A cache saves group player id so it might go faster with people with play more.
>

<img width="852" height="565" alt="groupraidui" src="https://github.com/user-attachments/assets/9bf8e21e-60d7-4491-bf83-9add86270b4d" />


## Download

[Download SC-RTLT Public 2.1.7 for Windows](https://github.com/neehhhh/SC-RTLT/releases/download/2.1.7/SC-RTLT_Public_2.1.7_Windows.zip)

SHA-256:

```text
d71f6ba67d980f20df9b8472dd726435621b3a0c25004fefa47d2d6502e9caaa
```

Windows SmartScreen may display a warning because the application is not
signed with a commercial code-signing certificate.

## Installation

1. Download and fully extract the ZIP archive.
2. Open the `SC-RTLT_Public_1.4.37_Windows` folder.
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

Radios featured:

- [HCN Radio](https://www.hcnradio.com/)
- [The People's Radio](https://thepeoplesradio.space)
- [REC·REG Radio](https://recreg.com)

## License

The source code in this repository is licensed under the
[GNU General Public License v3.0](LICENSE).
