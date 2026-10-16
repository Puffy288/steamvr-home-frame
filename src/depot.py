"""Ask the signed-in Steam client to download licensed Home content."""
import json
from pathlib import Path
import re
import time

from common import DEPOTS, find_depot, find_fex


def command(ui, text):
    ui.evaluate('''(()=>{
      window.__frameHomeDownloadHandle?.unregister();
      window.__frameHomeDownloadLines=[];
      window.__frameHomeDownloadHandle=SteamClient.Console.RegisterForSpewOutput(line=>{
        window.__frameHomeDownloadLines.push(line);
        if(window.__frameHomeDownloadLines.length>400)window.__frameHomeDownloadLines.shift();
      });
      SteamClient.Console.ExecCommand(COMMAND);
      return true;
    })()'''.replace('COMMAND', json.dumps(text)))


def stop_listening(ui):
    ui.evaluate('''(()=>{window.__frameHomeDownloadHandle?.unregister();
      delete window.__frameHomeDownloadHandle; delete window.__frameHomeDownloadLines; return true})()''')


def ensure_depot(ui, steam, depot):
    progress = Path.home() / '.cache/steamvr-home-frame'
    progress.mkdir(parents=True, exist_ok=True)
    pending = progress / f'depot-{depot}.pending'
    existing = find_depot(steam, depot)
    if existing and not pending.exists():
        print(f'Reusing Home depot {depot}.', flush=True)
        return existing
    print(f'Downloading Home depot {depot} through Steam. This can take several minutes.', flush=True)
    pending.write_text(DEPOTS[depot] + '\n')
    command(ui, f'download_depot 250820 {depot} {DEPOTS[depot]}')
    try:
        deadline = time.monotonic() + 7200
        previous = ''
        while time.monotonic() < deadline:
            lines = ui.evaluate('window.__frameHomeDownloadLines.splice(0)')
            for item in lines:
                # The Steam callback is an object; preserve its text regardless of field spelling.
                text = item if isinstance(item, str) else item.get('spew', json.dumps(item))
                if str(depot) in text or 'Depot download' in text or 'ERROR' in text:
                    if text != previous:
                        print(text, flush=True)
                        previous = text
                if re.search(r'(Depot download failed|Failed to (download|load)|Access Denied|No subscription|not available|Missing license)', text, re.I):
                    raise RuntimeError('Steam could not download Home: ' + text)
                if 'Depot download complete' in text and f'depot_{depot}' in text:
                    result = find_depot(steam, depot)
                    if result:
                        pending.unlink(missing_ok=True)
                        return result
                    raise RuntimeError('Steam completed the depot in an unrecognized location.')
            time.sleep(2)
        raise RuntimeError('Download timed out. Check Steam Downloads, then run the installer again.')
    finally:
        stop_listening(ui)


def ensure_fex(ui, steam):
    result = find_fex(steam)
    if result:
        return result
    print('Installing Valve\'s FEX runtime through Steam...', flush=True)
    command(ui, 'app_install 3127680')
    try:
        for _ in range(900):
            result = find_fex(steam)
            if result:
                return result
            lines = ui.evaluate('window.__frameHomeDownloadLines.splice(0)')
            for line in lines:
                text = line if isinstance(line, str) else line.get('spew', json.dumps(line))
                if re.search(r'(failed|Access Denied|No subscription|Missing license)', text, re.I):
                    raise RuntimeError('FEX installation failed: ' + text)
            time.sleep(2)
    finally:
        stop_listening(ui)
    raise RuntimeError('FEX installation timed out. Finish its Steam download and run the installer again.')
