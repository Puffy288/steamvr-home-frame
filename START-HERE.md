# Install using the Frame controllers

Reading this on your PC? Open this same GitHub page in Chromium on your Frame. The installer needs to be downloaded onto the headset.

## 1. Open the desktop

1. Put on the Frame, connect to Wi-Fi, and sign in to Steam.
2. Press the controller’s **Steam button** to open the dashboard.
3. Select **+ (Launch Program) → Desktop** in the dashboard’s dock.

Point at an item and pull the trigger to click it. Press the thumbstick inward to open its right-click menu, then point at a menu item and pull the trigger to select it. These are the default controller actions.

## 2. Open the project in Chromium

Open the desktop’s **application menu at the bottom left**, search for **Chromium**, and select it. Chromium is the web browser. If you see **Install Chromium**, select that first and follow its Install button.

Select the browser’s address bar, open the VR window’s on-screen keyboard, and enter this project’s GitHub address. Select **Enter** on the on-screen keyboard to open the page. Keep this guide open so you can copy the command below.

## 3. Download the installer

On the project page, open **Releases → newest release → Assets**. Download **SteamVR-Home-Frame-Install.run** into **Downloads** and wait for it to finish. You do not need the “Source code” ZIP or a GitHub account to download it.

Keep Steam running and signed in. Setup handles the remaining downloads, including Valve’s FEX runtime if it is missing.

## 4. Copy the command with your controller

```bash
bash ~/Downloads/SteamVR-Home-Frame-Install.run
```

1. Point at the start of the command above. Hold the trigger and drag across the whole line to select it, then release the trigger.
2. With the pointer over the selected text, press the thumbstick inward to open the right-click menu.
3. Point at **Copy** and pull the trigger.

## 5. Paste it into Konsole

Open the desktop’s application menu, search for **Konsole**, and select it. Konsole is the terminal window shown below.

![Konsole open in the Steam Frame dashboard](docs/screenshots/konsole-on-frame.jpg)

1. Point inside the dark terminal area and pull the trigger to select it.
2. Press the thumbstick inward to open the right-click menu.
3. Point at **Paste** and pull the trigger. The command should appear after the prompt.
4. Open the VR window’s on-screen keyboard using its keyboard button, then select **Enter** to run the command.

No administrator password is needed. Leave Konsole open until it says **Installed**.

## 6. Play

Press **Steam**, then open **Library → Non-Steam → SteamVR Home (Frame - Unofficial) → Play**. Future launches only need this library entry. You can close Chromium and Konsole once setup finishes.

To close Home, select it in **Currently Running Games** and choose **Stop**.

## If something gets stuck

- **No such file or directory:** check Downloads for the exact installer filename and wait for the download to finish.
- **Cannot reach Steam:** enable **CEF Remote Debugging** in Steam’s **Developer** settings, restart Steam, and run the command again. Some versions first need Developer Mode. You can turn remote debugging off after setup; playing does not need it.
- **Slow first run:** Steam may be downloading and unpacking your subscribed Workshop environments. Let that finish, or pause downloads in Steam. Heavy environments can still be slow.

## Where it installs

The launcher, private settings, compatibility files, and logs go in `~/.local/share/steamvr-home-frame/`. Setup downloads are cached in `~/.cache/steamvr-home-frame/`. Official Home files and Valve’s FEX runtime go in your Steam library. Here, `~` means your home folder.

The installer prints the exact locations. [Read the full list of system changes](SYSTEM-CHANGES.md) for the details.

If you need to uninstall later, close Home and copy this command into Konsole using the same controller steps above:

```bash
bash ~/.local/share/steamvr-home-frame/Uninstall.sh
```

This removes the library entry and keeps the private folder as `steamvr-home-frame.uninstalled` beside the original. Shared Steam downloads, FEX, and Workshop content stay in place. Automatic shortcut removal needs the same local Steam interface as setup.

[Back to the overview and screenshots](README.md).
