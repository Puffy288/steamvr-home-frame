# System changes

Setup runs as the normal Steam user. It does not need sudo and does not modify the kernel, firmware, thermal limits, system root filesystem or global Vulkan configuration.

## Downloads and files

The signed-in Steam client downloads SteamVR application 250820 depots:

| Depot | Pinned manifest | Content |
| --- | --- | --- |
| 250830 | 1874458903680892192 | Home assets |
| 250832 | 3112697343985428860 | Linux Home executable and libraries |

Only entries in Steam's matching cached manifest are eligible. Each selected file's size and SHA-1 content digest are checked. Unlisted files, including old user saves and generated configuration in a reused depot, are excluded. Immutable files are linked from the private layout; writable configuration and the main executable are copied. Private quality edits replace links atomically so they do not write into the shared depot.

Valve's FEX runtime is found in the Steam libraries or requested through Steam (application 3127680). Required compatibility libraries are downloaded from Valve's package server using the exact URLs, sizes and SHA-256 hashes in `packages.lock.json`. Package installation scripts are not run; only needed libraries and license notices are extracted privately.

The installer creates `~/.local/share/steamvr-home-frame/` and uses `~/.cache/steamvr-home-frame/`. Steam's official download cache and FEX are shared resources. Setup applies Valve's SteamVR Home artwork to the new shortcut.

## Steam and VR integration

The library shortcut is named **SteamVR Home (Frame - Unofficial)**. It is registered as a VR application using the shortcut's own app key, including the native ARM executable field required by Frame. Content and Workshop requests retain SteamVR's application ID. The launcher does not force a particular room or change subscriptions.

The launcher may briefly request Workshop metadata through the native Steam API before starting Home. Failed or offline requests fall back to normal startup.

Setup and uninstall use Steam's local developer interface for shortcut management. The tool accepts only a loopback connection and rejects redirects. It does not replace `shortcuts.vdf` or rewrite unrelated shortcuts. Steam's CEF Remote Debugging setting may need to be enabled manually; it is not required for ordinary launches.

## Rendering and audio

The launcher uses Valve's FEX with its native Vulkan forwarding libraries where available. Audio connects to the user's existing PulseAudio/PipeWire service. No audio services are restarted.

The profile retains 4× MSAA, uses 16× anisotropic filtering and a 1.05 render scale. The actual eye dimensions depend on the runtime's recommendation. Sun shadow maximum is configured to 1536 and its atlas to 4096, preserving shadow draw distance, lighting and other major features.

Our private Vulkan adapter corrects coverage in a specific optional alpha-tested depth pass. It does not replace the final colour rendering with a smoothing filter. Known game files and the adapter are hash-checked before enabling the optimization. An unsupported build or missing adapter disables that optional prepass. On a matched-pipeline creation failure, the adapter falls back to a depth pass that writes no depth. This favours correct colour rendering over the optimization's performance benefit.

The compiled ARM64 library and shader are our own code, shipped with source. Only this Home process receives the layer settings. No layer is installed globally. The release contains no Valve executable, extracted Valve shader or modified Valve script.

## Startup, stopping and removal

Steam Stop asks the matching Home window to close normally so preferences can be saved. If it fails to exit, a bounded fallback terminates that verified process. This does not guarantee every scripted room can shut down cleanly.

Steam Cloud account data is separate from the private installation. A fresh install can restore an older cloud-saved room even though no local settings were copied. Setup does not delete cloud saves or change subscriptions.

Uninstall removes only the verified shortcut and this installation's VR registration, then renames the private directory to `.uninstalled`. It leaves the shared depots, FEX, Workshop content and other Home variants in place. An existing `.uninstalled` backup must be preserved elsewhere before another uninstall.

Logs can contain local paths and Steam identifiers. Review them before sharing. No personal development logs are included in the public package.
