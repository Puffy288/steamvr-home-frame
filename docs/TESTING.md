# Testing

Version 2.0.0 was tested on one Steam Frame running SteamOS VR, using an existing Steam account and cached Valve and FEX downloads.

## Installation and use

Installation, uninstall and reinstallation completed successfully. Checks covered launching Home, menus, controllers, Workshop downloads, room transitions, saving a home environment and closing through Steam.

## Automated checks

- 32 Python tests covering archive handling, file hashes, configuration, shortcuts, process identity, graphics adapter guards and Workshop startup preparation.
- A CPU-only Vulkan test covering shader and partial pipeline failures and the fallback path.
- 1,959 selected Valve files checked against their depot manifests.
- Loader checks for 48 game and VR modules, plus the audio loader.
- ARM64 adapter rebuilt from the included source and matched to the shipped binary.
- Installer extraction and archive checksums verified.

These results cover the tested hardware and environments. They are not a performance benchmark for every Workshop environment.
