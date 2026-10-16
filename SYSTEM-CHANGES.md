# System changes

This page describes what setup installs and how the launcher works. For the short installation guide, start with [the README](README.md).

## Files created

| Location | Purpose |
| --- | --- |
| `~/.local/share/steamvr-home-frame/` | Private launcher, Python source, graphics profile, dependency libraries, notices, installation receipt, process state, logs, and merged game directory. |
| `~/.cache/steamvr-home-frame/` | Checksum-addressed dependency and artwork downloads, plus installer lock/progress files. |
| Steam's `steamapps/content/app_250820/depot_250830` and `depot_250832` | Official Home assets and Linux executables, if missing. On Frame these are commonly under Steam's `steamrtarm64` directory. |
| Steam's `steamapps/common/FEX-Emu/` | Valve's FEX runtime, if missing; requested as app 3127680. |
| Steam's shortcut data | One entry named **SteamVR Home (Frame - Unofficial)**, created through the running client. Existing entries are not rewritten by the installer. |
| Steam's current-user `userdata/<account>/config/grid/` | The official Home capsule used for this shortcut's portrait, copied through Steam's artwork API. |

Setup discovers your Steam libraries and records the install paths and shortcut ID in a local installation receipt.

## Download sources

Home is requested through the signed-in Steam client, app 250820. New downloads use these pinned manifests:

| Depot | Manifest |
| --- | --- |
| 250830, Home content | 1874458903680892192 |
| 250832, Linux application | 3112697343985428860 |

Existing depots are reused. Setup checks their module dependencies and waits for Steam to finish any new downloads. Steam handles authorization and content delivery through your signed-in account.

Valve’s FEX runtime is reused when installed. If it is missing, setup requests app 3127680 through Steam and waits for it. No separate FEX installation step is needed. The Frame’s SteamOS VR installation must supply `/usr/share/guestos/fex-mesa` and the SteamVR runtime in `/opt/steamvr`; setup checks for these before downloading anything.

The 17 small compatibility packages in `packages.lock.json` come from `https://repo.steampowered.com/steamrt1/apt/`. Their SHA-256 hashes, sizes, and versions are pinned from Valve's published runtime metadata. The package downloader extracts only architecture-checked x86-64 shared libraries and copyright notices into the private folder. It does not run Debian maintainer scripts or install `.deb` files into SteamOS. No libraries are bundled in the public source release.

The dependencies include libpng12, libva and its helpers, libvdpau, libXfixes, PulseAudio client libraries, and PulseAudio's dependencies. They are old compatibility libraries for this older application, not general-purpose replacements for system libraries. Package notices are saved in `third-party-notices/`; provenance is saved in `dependency-provenance.json`.

## Game layout and configuration

The installer creates a separate game directory using links to official depot files. The small main executable is copied so Home resolves its game root inside the private installation. Writable configuration is copied into that directory. The original depots are not patched.

The private graphics profile, `steamtours/vr_fidelity_levels_override.csv`, defines levels 0–8 with 4× MSAA and render scales 0.80–1.20. Home selects its active level dynamically. Rendering uses ordinary stereo with foveation off. Shadows, lighting, and scene effects are retained.

The launcher sets a library search path only for the guest Home process, points FEX to `/usr/share/guestos/fex-mesa`, uses `/opt/steamvr/bin/linux64/vrclient.so`, and connects the guest audio client to the current user's existing PulseAudio socket. Home receives app ID 250820 for SteamVR content and Workshop access, while preserving the shortcut game ID supplied by Steam. The outer launcher remains attached to the non-Steam library entry until Home exits.

Home writes its normal configuration, logs, caches, Steam Cloud data, and Workshop data. It uses its normal networking, including a local game-server socket. Steam manages subscribed Workshop downloads. Subscription choices and download controls remain in Steam.

Your chosen home environment is saved in Home’s private configuration and loaded at startup.

Optional library artwork is Valve's original `tools/content/steamvr_home_capsule_main.png`: the pavilion image with the Steam logo and HOME text. SteamVR's `tools/tools.vrmanifest` identifies this as Home's image. It is fetched unchanged from the public [SteamTracking mirror](https://github.com/SteamTracking/GameTracking-SteamVR/blob/76f1bd5ebdc45ae50824661d5430f8a9e5c71c40/tools/content/steamvr_home_capsule_main.png), hosted on GitHub, not Valve's download server. The URL is fixed to that commit. Its 149,503 bytes are pinned to SHA-256 `de5888c4e2f0db5822cbe3bdf245d583e7a195eec98ed0102d0566e852ccae30` and cached under `~/.cache/steamvr-home-frame/artwork/`. The downloader rejects redirects and changed/incomplete images. No artwork is bundled in this installer.

Setup copies the image into Steam's vertical-tile artwork slot and points this shortcut's list icon to the verified PNG in the artwork cache. Steam fits it to those slots. Deleting that cached PNG later removes the list icon until it is set again through the shortcut's properties. The wide banner keeps the **SteamVR Home (Frame - Unofficial)** text title. Setup skips artwork if Steam reports existing custom images or lacks the interface. Steam manages the copied images, which may remain cached after shortcut removal. Artwork failure does not prevent installation.

## Native graphics forwarding

When Valve's FEX install includes `GuestThunks/libvulkan-guest.so` and `HostThunks/libvulkan-host.so`, setup creates a private `vulkan/libvulkan.so.1` link to the guest library. The launcher puts that private folder first in Home's library path and sets `FEX_THUNKHOSTLIBS` and `FEX_THUNKGUESTLIBS` for its child process. This forwards Vulkan calls to the installed ARM64 driver. It does not patch the driver, the FEX root filesystem, or global FEX settings. Existing native Vulkan layers may also load according to their existing configuration.

If forwarding libraries are absent, Home uses the emulated x86 driver. The `--emulated-vulkan` launch option selects that fallback explicitly. No driver or extra forwarding binary is downloaded by this project.

## Desktop companion window

During the first 30 seconds of startup, the launcher uses the existing X11 library to find a window named `SteamVR Home` owned by the exact game process it started. It hides only that window and watches for startup remapping. It does not close it, alter other applications, or change headset resolution. The check ends after that window of time or when Home exits; no permanent service is installed.

The hidden window also disappears from the desktop taskbar. Close Home using **Stop** in Steam’s **Currently Running Games** or library entry. Use `--show-mirror` in launch options to keep the desktop window visible.

## Steam UI integration

Installation uses Steam’s local Chromium debugging endpoint at `127.0.0.1:8080` to request downloads and create the shortcut through `SteamClient`. The shortcut is marked as VR. A brief theater view may appear during startup on some Steam versions.

Temporary download callbacks are removed after each operation. If setup is forcibly closed, its callback may remain until setup runs again or Steam restarts. No persistent UI script or service is installed. The local interface is used for installation and shortcut removal; normal launches do not connect to it.

If the endpoint is disabled, setup stops with instructions to enable CEF Remote Debugging through Steam settings. Enabling that setting gives local applications access to a powerful client interface, so it may be turned off again after setup.

## Updates and uninstall

Dependencies and the private game tree are prepared in a temporary folder, then checked with FEX's x86-64 dynamic loader. The installed tree is replaced only after checks pass. Existing package configuration is retained during updates. The previous installation is kept beside the new one as a recoverable backup. Interrupted Steam downloads may remain in Steam's download directories; rerunning the installer can resume them.

A failed shortcut step leaves the complete private runtime in place so setup can be rerun. Installation does not stop/restart Steam or the native VR compositor. Stop Home before updating it.

Close Home and run `bash ~/.local/share/steamvr-home-frame/Uninstall.sh` to uninstall. The uninstaller checks that the shortcut still points to this package before removing it. It moves the private installation to `~/.local/share/steamvr-home-frame.uninstalled`, keeping your configuration and logs recoverable. You can delete that saved folder later.

Official depots, FEX, Workshop subscriptions/content, the download cache, and earlier update backups remain in place. Remove shared components only when nothing else needs them. To undo an update, restore the previous folder to the original install path while Home is stopped.

## Unchanged

- SteamOS's read-only system and package database.
- Native graphics drivers and the FEX system root filesystem.
- The native SteamVR server and compositor.
- Other game shortcuts, controller profiles, and installed mods.
- Global speaker/microphone settings and Workshop subscriptions.
- Services, startup tasks, and firewall configuration.
