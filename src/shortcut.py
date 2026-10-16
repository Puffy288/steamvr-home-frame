"""Add one shortcut through the running Steam client; never overwrite shortcuts.vdf."""
import json
import time

from common import APP_NAME


def details(ui, appid):
    return ui.evaluate('''new Promise((resolve,reject)=>{
        let handle;
        const timer=setTimeout(()=>{handle?.unregister();reject(new Error('App details timed out'))},10000);
        handle=SteamClient.Apps.RegisterForAppDetails(APPID, d=>{
            clearTimeout(timer);setTimeout(()=>handle?.unregister(),0);
            resolve({id:d.unAppID,name:d.strDisplayName,exe:d.strShortcutExe,
                directory:d.strShortcutStartDir,options:d.strLaunchOptions,vr:d.bShortcutIsVR,
                compat:d.strCompatToolName});
        });
    })'''.replace('APPID', str(int(appid))))


def add_shortcut(ui, install, prior=None):
    launcher = install / 'Launch.sh'
    exe = '"' + str(launcher) + '"'
    directory = '"' + str(install) + '"'
    entries = ui.evaluate('appStore.allApps.filter(a=>a.app_type===1073741824)'
                          '.map(a=>({id:a.appid,name:a.display_name}))')
    appid = None
    for entry in entries:
        if entry['name'] != APP_NAME and entry['id'] != prior:
            continue
        found = details(ui, entry['id'])
        if found.get('exe', '').strip('"') == str(launcher):
            appid = entry['id']
            break
        if entry['name'] == APP_NAME:
            raise RuntimeError('A different shortcut already uses the name ' + APP_NAME + '. Rename it first.')
    if appid is None:
        appid = ui.evaluate('SteamClient.Apps.AddShortcut(' + ','.join(map(json.dumps,
                               [APP_NAME, str(launcher), '', str(launcher)])) + ')')
        if not isinstance(appid, int) or appid <= 0:
            raise RuntimeError('Steam did not return a shortcut ID: ' + repr(appid))
        ui.evaluate(f'SteamClient.Apps.SetShortcutLaunchOptions({appid}, "")')
    settings = {'id': appid, 'name': APP_NAME, 'exe': exe, 'directory': directory}
    ui.evaluate('''(cfg=>{
        const id=cfg.id;
        SteamClient.Apps.SetShortcutName(id,cfg.name);
        SteamClient.Apps.SetShortcutExe(id,cfg.exe);
        SteamClient.Apps.SetShortcutStartDir(id,cfg.directory);
        SteamClient.Apps.SetShortcutIsVR(id,true);
        SteamClient.Apps.SpecifyCompatTool(id,"");
        return true;
    })(''' + json.dumps(settings) + ')')
    for _ in range(10):
        found = details(ui, appid)
        if (found.get('exe') == exe and found.get('name') == APP_NAME
                and found.get('vr')):
            return appid
        time.sleep(0.2)
    raise RuntimeError('The shortcut was added, but its VR settings could not be verified. Run installer again.')


def remove_shortcut(ui, install, appid):
    entries = ui.evaluate('appStore.allApps.filter(a=>a.app_type===1073741824).map(a=>a.appid)')
    if appid not in entries:
        return
    found = details(ui, appid)
    if found.get('exe', '').strip('"') != str(install / 'Launch.sh'):
        raise RuntimeError('Shortcut target has changed; remove it manually to preserve your changes.')
    ui.evaluate(f'SteamClient.Apps.RemoveShortcut({int(appid)})')
