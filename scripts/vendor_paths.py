"""Put bundled third-party packages in vendor/ onto sys.path.

Third-party tools are tracked as git submodules under vendor/ so they can be updated
with `git submodule update --remote` instead of being copied in by hand. Their import
root is usually one level below the submodule root (vendor/dwpicker/dwpicker is the
package, so vendor/dwpicker is what belongs on sys.path).

Paths are derived from this file's location, so the repo can be cloned anywhere.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(REPO_ROOT, "vendor")


def add(*relative_parts):
    """Prepend <repo>/vendor/<parts...> to sys.path if it exists and isn't already on it.

    Returns:
        str or None: the path added (or already present), None if it does not exist.
    """
    path = os.path.normpath(os.path.join(VENDOR, *relative_parts))
    if not os.path.isdir(path):
        print("[MayaTools] vendor path missing: %s\n"
              "            run: git submodule update --init --recursive" % path)
        return None
    if path not in sys.path:
        sys.path.insert(0, path)
    return path


def ensure_dwpicker():
    """Make `import dwpicker` work from the bundled submodule."""
    return add("dwpicker")
