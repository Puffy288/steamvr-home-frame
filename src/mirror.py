"""Hide only this process's X11 companion window during startup.

This removes the desktop presentation, not the headset's rendering targets.
It does not claim to eliminate all internal mirror rendering work.
"""
import ctypes as C
import ctypes.util


def hide_companion(pid, finished, close=False):
    display = None
    try:
        library = ctypes.util.find_library('X11')
        if not library:
            print('Mirror: X11 is unavailable; leaving window unchanged.', flush=True)
            return
        x = C.CDLL(library)
        ptr, ulong, integer = C.c_void_p, C.c_ulong, C.c_int
        specs = {
            'XOpenDisplay': ([C.c_char_p], ptr),
            'XDefaultRootWindow': ([ptr], ulong),
            'XInternAtom': ([ptr, C.c_char_p, integer], ulong),
            'XQueryTree': ([ptr, ulong, C.POINTER(ulong), C.POINTER(ulong),
                           C.POINTER(C.POINTER(ulong)), C.POINTER(C.c_uint)], integer),
            'XGetWindowProperty': ([ptr, ulong, ulong, C.c_long, C.c_long, integer,
                                    ulong, C.POINTER(ulong), C.POINTER(integer),
                                    C.POINTER(ulong), C.POINTER(ulong), C.POINTER(ptr)], integer),
            'XFetchName': ([ptr, ulong, C.POINTER(ptr)], integer),
            'XUnmapWindow': ([ptr, ulong], integer),
            'XSendEvent': ([ptr, ulong, integer, C.c_long, ptr], integer),
            'XFlush': ([ptr], integer), 'XSync': ([ptr, integer], integer),
            'XFree': ([ptr], integer), 'XCloseDisplay': ([ptr], integer),
        }
        for name, (arguments, result) in specs.items():
            getattr(x, name).argtypes = arguments
            getattr(x, name).restype = result
        # Windows can disappear between enumeration and inspection. Handle that
        # expected X error locally instead of allowing Xlib to exit the launcher.
        handler_type = C.CFUNCTYPE(integer, ptr, ptr)
        handler = handler_type(lambda d, error: 0)
        x.XSetErrorHandler.argtypes = [ptr]
        x.XSetErrorHandler.restype = ptr
        previous_handler = x.XSetErrorHandler(C.cast(handler, ptr))
        try:
            display = x.XOpenDisplay(None)
            if not display:
                print('Mirror: no X11 display; leaving window unchanged.', flush=True)
                return
            root = x.XDefaultRootWindow(display)
            atom = x.XInternAtom(display, b'_NET_WM_PID', 1)
            if not atom:
                return

            def children(window):
                root_out, parent = ulong(), ulong()
                values, count = C.POINTER(ulong)(), C.c_uint()
                if not x.XQueryTree(display, window, C.byref(root_out), C.byref(parent), C.byref(values), C.byref(count)):
                    return []
                result = list(values[:count.value]) if values else []
                if values:
                    x.XFree(values)
                return result

            def matches(window):
                actual_type, count, remaining = ulong(), ulong(), ulong()
                fmt, data = integer(), ptr()
                result = x.XGetWindowProperty(display, window, atom, 0, 1, 0, 0,
                                               C.byref(actual_type), C.byref(fmt), C.byref(count),
                                               C.byref(remaining), C.byref(data))
                try:
                    if result or fmt.value != 32 or count.value != 1 or not data:
                        return False
                    owner = C.cast(data, C.POINTER(ulong))[0]
                    if owner != pid:
                        return False
                finally:
                    if data:
                        x.XFree(data)
                title = ptr()
                x.XFetchName(display, window, C.byref(title))
                try:
                    return bool(title) and C.string_at(title) == b'SteamVR Home'
                finally:
                    if title:
                        x.XFree(title)

            hidden = False
            # Catch the first window before Steam promotes it to a theater
            # overlay. Keep watching briefly in case startup maps it again.
            for _ in range(1 if close else 300):
                if finished.is_set():
                    return
                candidates = children(root)
                for window in list(candidates):
                    candidates.extend(children(window))
                for window in candidates:
                    if matches(window) and not finished.is_set():
                        if close:
                            class ClientMessage(C.Structure):
                                _fields_ = [('type', integer), ('serial', ulong),
                                            ('send_event', integer), ('display', ptr),
                                            ('window', ulong), ('message_type', ulong),
                                            ('format', integer), ('data', C.c_long * 5)]
                            class Event(C.Union):
                                _fields_ = [('client', ClientMessage), ('padding', C.c_long * 24)]
                            event = Event()
                            event.client.type = 33  # X11 ClientMessage
                            event.client.send_event = 1
                            event.client.display = display
                            event.client.window = window
                            event.client.message_type = x.XInternAtom(display, b'WM_PROTOCOLS', 0)
                            event.client.format = 32
                            event.client.data[0] = x.XInternAtom(display, b'WM_DELETE_WINDOW', 0)
                            x.XSendEvent(display, window, 0, 0, C.byref(event))
                            x.XSync(display, 0)
                            print('Asked Home to save and close normally.', flush=True)
                            return True
                        x.XUnmapWindow(display, window)
                        x.XSync(display, 0)
                        if not hidden:
                            print('Home desktop companion hidden. Close Home with Stop in its Steam library entry.', flush=True)
                        hidden = True
                if finished.wait(.1):
                    return
            if not hidden:
                print('Mirror: no matching Home window found; no windows changed.', flush=True)
        finally:
            if display:
                x.XCloseDisplay(display)
            x.XSetErrorHandler(previous_handler)
    except (OSError, AttributeError) as exc:
        print('Mirror hiding unavailable:', exc, flush=True)


if __name__ == '__main__':
    import sys
    import threading
    if len(sys.argv) == 3 and sys.argv[1] == '--close':
        sys.exit(0 if hide_companion(int(sys.argv[2]), threading.Event(), close=True) else 1)
    sys.exit('Usage: mirror.py --close PID')
