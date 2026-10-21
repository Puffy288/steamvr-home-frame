"""Prepare saved-home Workshop metadata before Home chooses its first map.

Uses the installed ARM Steam API in a bounded child process. No subscription,
content, save, or global Steam setting is changed. Home keeps choosing its own
saved environment; failed/offline preparation falls back to normal startup.
"""
import ctypes as C
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from common import write_json


def saved_workshop_id(install):
    try:
        text = (install / 'game/steamtours/cfg/machine_vr.vcfg').read_text()
    except (OSError, UnicodeError):
        return None
    pairs = re.findall(r'^\s*"(steamvrhome_home_map(?:_addon|_type)?)"\s*"([^"\r\n]*)"\s*$', text, re.M)
    values = dict(pairs)
    if len(values) != len(pairs) or values.get('steamvrhome_home_map_type') not in ('4', '5', '9'):
        return None
    item = values.get('steamvrhome_home_map_addon', '')
    if not re.fullmatch(r'[1-9][0-9]{0,19}', item) or int(item) >= 2**64:
        return None
    return int(item)


def prepare(install, vr, env):
    item = saved_workshop_id(install)
    if item is None:
        return
    child_env = env.copy()
    child_env.update(SteamAppId='250820')
    # Native helper must not inherit the x86 game's library overrides.
    child_env.pop('LD_PRELOAD', None)
    child_env.pop('LD_LIBRARY_PATH', None)
    result = {'item': item, 'ready': False}
    try:
        run = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                              '--query', str(vr / 'bin/linuxarm64/libsteam_api.so'), str(item)],
                             env=child_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, timeout=15)
        for line in reversed(run.stdout.splitlines()):
            if line.startswith('{'):
                result.update(json.loads(line))
                break
        result['ready'] = bool(result.get('ready') and run.returncode == 0)
        result['exit_code'] = run.returncode
    except subprocess.TimeoutExpired:
        result['reason'] = 'Workshop preparation timed out; normal Home startup retained.'
    except (OSError, ValueError) as exc:
        result['reason'] = str(exc)
    try:
        write_json(install / 'logs/workshop-startup.json', result)
    except OSError:
        pass
    print('Saved-home Workshop data prepared.' if result['ready'] else
          'Workshop preparation unavailable; using normal Home startup.', flush=True)


def query(library, item):
    api = C.CDLL(str(library))
    def fn(name, result, *args):
        f = getattr(api, name)
        f.restype, f.argtypes = result, list(args)
        return f
    ptr, u64, u32, boolean = C.c_void_p, C.c_uint64, C.c_uint32, C.c_bool
    error = C.create_string_buffer(1024)
    status = fn('SteamAPI_InitFlat', C.c_int, ptr)(error)
    if status:
        raise RuntimeError('Steam API initialization unavailable: ' + str(status))
    handle = None
    started = time.monotonic()
    try:
        ugc = fn('SteamAPI_SteamUGC_v021', ptr)()
        utils = fn('SteamAPI_SteamUtils_v010', ptr)()
        if not ugc or not utils:
            raise RuntimeError('Required installed Steam API interfaces unavailable.')
        count = fn('SteamAPI_ISteamUGC_GetNumSubscribedItems', u32, ptr, boolean)(ugc, False)
        if count > 4096:
            raise RuntimeError('Unexpected Workshop subscription count.')
        items = (u64 * max(1, count))()
        received = fn('SteamAPI_ISteamUGC_GetSubscribedItems', u32, ptr, C.POINTER(u64), u32, boolean)(
            ugc, items, count, False)
        values = list(dict.fromkeys([item] + list(items)[:received]))
        ids = (u64 * len(values))(*values)
        handle = fn('SteamAPI_ISteamUGC_CreateQueryUGCDetailsRequest', u64, ptr, C.POINTER(u64), u32)(
            ugc, ids, len(values))
        if handle in (0, 2**64 - 1):
            raise RuntimeError('Workshop query unavailable.')
        fn('SteamAPI_ISteamUGC_SetAllowCachedResponse', boolean, ptr, u64, u32)(ugc, handle, 3600)
        call = fn('SteamAPI_ISteamUGC_SendQueryUGCRequest', u64, ptr, u64)(ugc, handle)
        if not call:
            raise RuntimeError('Workshop query could not start.')
        pump = fn('SteamAPI_RunCallbacks', None)
        completed = fn('SteamAPI_ISteamUtils_IsAPICallCompleted', boolean, ptr, u64, C.POINTER(boolean))
        failed = boolean()
        while time.monotonic() - started < 12:
            pump()
            if completed(utils, call, C.byref(failed)):
                break
            time.sleep(.1)
        else:
            raise RuntimeError('Workshop metadata query timed out.')
        if failed.value:
            raise RuntimeError('Workshop metadata connection failed.')
        # SteamUGCDetails_t includes an 8000-byte description plus title, tags,
        # paths and other fields. Reserve 64 KiB for the pinned v021 interface;
        # only read its documented, naturally aligned ID/result prefix.
        details = C.create_string_buffer(65536)
        success = fn('SteamAPI_ISteamUGC_GetQueryUGCResult', boolean, ptr, u64, u32, ptr)(
            ugc, handle, 0, details)
        found_id = C.c_uint64.from_buffer(details).value
        found_result = C.c_int32.from_buffer(details, 8).value
        return {'ready': bool(success and found_id == item and found_result == 1),
                'item': item, 'result': found_result, 'requested': len(values),
                'seconds': round(time.monotonic() - started, 3)}
    finally:
        if handle not in (None, 0, 2**64 - 1):
            fn('SteamAPI_ISteamUGC_ReleaseQueryUGCRequest', boolean, ptr, u64)(ugc, handle)
        fn('SteamAPI_Shutdown', None)()


if __name__ == '__main__':
    try:
        if len(sys.argv) != 4 or sys.argv[1] != '--query':
            raise ValueError('Expected --query installed-library-path item-id')
        item = int(sys.argv[3])
        if not 0 < item < 2**64:
            raise ValueError('Invalid Workshop item ID')
        print(json.dumps(query(Path(sys.argv[2]), item)), flush=True)
    except (OSError, RuntimeError, AttributeError, ValueError) as exc:
        print(json.dumps({'ready': False, 'reason': str(exc)}), flush=True)
        sys.exit(1)
