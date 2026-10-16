"""Optional original Valve Home capsule, fetched from a pinned public mirror."""
import base64
import hashlib
import json
import os
import tempfile
import urllib.request

from shortcut import details


ART_URL = ('https://raw.githubusercontent.com/SteamTracking/GameTracking-SteamVR/'
           '76f1bd5ebdc45ae50824661d5430f8a9e5c71c40/'
           'tools/content/steamvr_home_capsule_main.png')
ART_SHA256 = 'de5888c4e2f0db5822cbe3bdf245d583e7a195eec98ed0102d0566e852ccae30'
ART_SIZE = 149503


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError('Artwork redirects are not accepted.')


def official_capsule(cache):
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / (ART_SHA256 + '.png')
    data = b''
    if not path.is_symlink() and path.is_file() and path.stat().st_size == ART_SIZE:
        data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() == ART_SHA256:
        return data
    opener = urllib.request.build_opener(NoRedirects())
    with opener.open(ART_URL, timeout=15) as response:
        data = response.read(ART_SIZE + 1)
    if len(data) != ART_SIZE or hashlib.sha256(data).hexdigest() != ART_SHA256:
        raise RuntimeError('Official Home artwork changed or download is incomplete.')
    fd, temporary = tempfile.mkstemp(prefix='.home-art-', dir=cache)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return data


def apply_official_artwork(ui, cache, install, appid):
    """Keep existing custom art; set the vertical tile and list icon only."""
    appid = int(appid)
    if details(ui, appid).get('exe', '').strip('"') != str(install / 'Launch.sh'):
        raise RuntimeError('Artwork target does not belong to this installation.')
    state = ui.evaluate('''(()=>{
        const app=appStore.GetAppOverviewByAppID(APPID);
        return {supported:typeof SteamClient.Apps.SetCustomArtworkForApp==="function"
                && typeof SteamClient.Apps.SetShortcutIcon==="function",
            custom:typeof app?.BHasCustomImages==="function" ? app.BHasCustomImages() : null};
    })()'''.replace('APPID', str(appid)))
    if not state or not state.get('supported') or state.get('custom') is not False:
        return []
    data = official_capsule(cache)
    payload = json.dumps(base64.b64encode(data).decode('ascii'))
    ui.evaluate(f'SteamClient.Apps.SetCustomArtworkForApp({appid},{payload},"png",0)')
    icon_path = json.dumps(str(cache / (ART_SHA256 + '.png')))
    ui.evaluate(f'SteamClient.Apps.SetShortcutIcon({appid},{icon_path})')
    return ['Home cover', 'Home list icon']
