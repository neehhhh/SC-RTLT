# Privacy

This document describes the behavior of SC-RTLT Public 1.3.5 as implemented in
the source code in this repository.

## Game.log

SC-RTLT reads the local Star Citizen `Game.log` file in read-only mode to
detect location information. The complete log is not copied, archived, added
to the community registry, or uploaded by SC-RTLT.

## Manual location capture

No registry entry is written without a player action. When the player confirms
the Wi-Fi action, SC-RTLT stores the entered place name, the most likely
location code, and minimal technical context.

The registry excludes the player's name, account identifier, complete log, and
complete `Game.log` path. It is stored locally at:

```text
%LOCALAPPDATA%\SCRTLTPublicData\registry\SC-RTLT_Public_Registry.json
```

SC-RTLT does not upload this file automatically. The player decides whether to
share it.

## Embedded browser

The embedded Chromium browser connects directly to the websites the player
opens. Those external services receive ordinary web-request information and
apply their own privacy policies. When persistent browsing is enabled, browser
cookies and cache are stored locally in the SC-RTLT data directory.

Optional saved website credentials remain on the computer and are encrypted
with Windows Data Protection API (DPAPI) for the current Windows user. SC-RTLT
does not synchronize them to an SC-RTLT server.

## Radio streams

The player connects directly to independent radio-stream providers. Those
providers receive ordinary connection information and apply their own privacy
policies. SC-RTLT does not proxy or re-host the audio streams.

## Updates

The update check runs when the player uses the update control. SC-RTLT then
contacts the public GitHub Releases API for `neehhhh/SC-RTLT`, downloads the
selected release asset from GitHub, and verifies it against the published
SHA-256 checksum when the checksum asset is available.

SC-RTLT does not include a GitHub account token.
