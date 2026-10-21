"""Register this shortcut with the installed native OpenVR runtime."""
import ctypes as C
import os
from pathlib import Path

from common import APP_NAME, write_json


def manifest(install, appid):
    if not isinstance(appid, int) or not 0x80000000 <= appid <= 0xffffffff:
        raise RuntimeError('A valid non-Steam shortcut ID is required.')
    path = install / 'port2.vrmanifest'
    application = {
        'app_key': 'steam.app.' + str(appid),
        'launch_type': 'binary',
        'binary_path_linux': str(install / 'Launch.sh'),
        # The native Frame runtime selects this field, not binary_path_linux.
        'binary_path_linux_arm': str(install / 'Launch.sh'),
        'working_directory': str(install),
        'is_dashboard_overlay': False,
        'strings': {'en_us': {'name': APP_NAME,
                             'description': 'Independent SteamVR Home installation for Steam Frame.'}},
    }
    cover = install / 'home-cover.png'
    if cover.is_file() and not cover.is_symlink():
        application['image_path'] = str(cover.absolute())
    write_json(path, {'source': 'builtin', 'applications': [application]})
    return path


def register(install, appid, vr, remove=False):
    path = install / 'port2.vrmanifest' if remove else manifest(install, appid)
    if remove and not path.exists():
        return
    library = Path(vr) / 'bin/linuxarm64/libopenvr_api.so'
    api = C.CDLL(str(library))
    error = C.c_int()
    api.VR_InitInternal.argtypes = [C.POINTER(C.c_int), C.c_int]
    api.VR_InitInternal.restype = C.c_uint32
    api.VR_ShutdownInternal.argtypes = []
    api.VR_ShutdownInternal.restype = None
    api.VR_GetGenericInterface.argtypes = [C.c_char_p, C.POINTER(C.c_int)]
    api.VR_GetGenericInterface.restype = C.c_void_p
    # VRApplication_Background = 3. This helper never acquires scene focus.
    api.VR_InitInternal(C.byref(error), 3)
    if error.value:
        raise RuntimeError('SteamVR initialization failed: ' + str(error.value))
    try:
        # These are the first two functions in Valve's versioned C ABI table.
        address = api.VR_GetGenericInterface(b'FnTable:IVRApplications_007', C.byref(error))
        if error.value or not address:
            raise RuntimeError('OpenVR applications interface is unavailable: ' + str(error.value))
        table = C.cast(address, C.POINTER(C.c_void_p))
        encoded = os.fsencode(path.absolute())
        if remove:
            result = C.CFUNCTYPE(C.c_int, C.c_char_p)(table[1])(encoded)
        else:
            result = C.CFUNCTYPE(C.c_int, C.c_char_p, C.c_bool)(table[0])(encoded, False)
        if result:
            raise RuntimeError('OpenVR application registration failed: ' + str(result))
        if not remove:
            # AddApplicationManifest can succeed while skipping an invalid entry.
            # Verify the accepted executable, not just the returned error code
            # or IsApplicationInstalled (a running app can create a builtin entry).
            value = C.create_string_buffer(4096)
            app_error = C.c_int()
            get_string = C.CFUNCTYPE(C.c_uint32, C.c_char_p, C.c_int,
                                    C.c_void_p, C.c_uint32, C.POINTER(C.c_int))(table[14])
            get_string(('steam.app.' + str(appid)).encode(), 13,
                       value, len(value), C.byref(app_error))
            if app_error.value or os.fsdecode(value.value) != str(install / 'Launch.sh'):
                raise RuntimeError('SteamVR did not accept the Home executable registration.')
    finally:
        api.VR_ShutdownInternal()
