"""Generate shelves/shelf_MayaTools.mel from the button table below.

Editing a shelf by hand in Maya writes it to your prefs, not to this repo, and the two
then drift. So the shelf is generated from this file instead: change the table, re-run
`mayapy build_shelf.py`, commit the result.

    mayapy build_shelf.py
"""
import os

SHELF_NAME = "MayaTools"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "shelves", "shelf_%s.mel" % SHELF_NAME)

# label, annotation, icon (bare filename, resolved via XBMLANGPATH), overlay, sourceType, command
BUTTONS = [
    # ---- animation -------------------------------------------------------
    dict(
        label="animBot",
        annotation="animBot Toggle - show/hide the animBot menu",
        icon="animbot.png",
        source="python",
        command="from animBot._api.core import CORE as ANIMBOT_CORE\n"
                "ANIMBOT_CORE.trigger.animBotMenu_toggle()",
    ),
    dict(
        label="dwpicker",
        annotation="dwpicker - animation picker",
        icon="dwpicker.png",
        source="python",
        # dwpicker is a git submodule under vendor/. The importable package is
        # vendor/dwpicker/dwpicker, so its PARENT goes on sys.path - a plain
        # "import dwpicker" raises ModuleNotFoundError.
        command="import vendor_paths\n"
                "vendor_paths.ensure_dwpicker()\n"
                "import dwpicker\n"
                "dwpicker.show()",
    ),
    dict(
        label="Overlapper",
        annotation="Overlapper 1.1.2 - overlapping action",
        icon="overlapper.png",
        source="mel",
        command='source "overlapper.mel"; OverlapperRelease;',
    ),
    # ---- modelling / display --------------------------------------------
    dict(
        label="FCM_Hider",
        annotation="FCM_Hider - hide and isolate face components",
        icon="fcm_hidder.png",
        source="python",
        # show() publishes the module's functions into __main__ first, because the UI
        # is wired with string callbacks that Maya evaluates there.
        command="import importlib\n"
                "import fcm_hider\n"
                "importlib.reload(fcm_hider)\n"
                "fcm_hider.show()",
    ),
    dict(
        label="SpeedCut",
        annotation="SpeedCut 2.24 - boolean / cut tool set (Joe Wu)",
        # placeholder: pie_chart.png is reserved for the geometry slicer
        icon="manriki.png",
        source="python",
        # show() publishes the module's names into __main__ first - SpeedCut's UI is
        # wired with 85 string callbacks, which Maya evaluates there.
        command="import importlib\n"
                "import speedcut\n"
                "importlib.reload(speedcut)\n"
                "speedcut.show()",
    ),
    # ---- BanditCamp ------------------------------------------------------
    dict(
        label="Rig Replicator",
        annotation="Rig Replicator - duplicate a rigged character cleanly",
        icon="rig_replicator.png",
        source="python",
        command="import bc_rig_replicator as bcr\n"
                "from importlib import reload; reload(bcr)\n"
                "bcr.show()",
    ),
    dict(
        label="Locomotion",
        annotation="Generate directional walk variants from RunForward",
        icon="locomotion.png",
        source="python",
        command="import bc_locomotion_variants as bcl\n"
                "from importlib import reload; reload(bcl)\n"
                "bcl.show()",
    ),
    dict(
        label="Anim Exporter",
        annotation="Animation Exporter - bookmarks to FBX",
        icon="exporter.png",
        source="python",
        command="import bc_anim_exporter as bce\n"
                "from importlib import reload; reload(bce)\n"
                "bce.show()",
    ),
    dict(
        label="Speed Ref",
        annotation="Unity Speed Reference - visualize Unity speed values",
        icon="unity_speed.png",
        source="python",
        command="import bc_speed_reference as bcs\n"
                "from importlib import reload; reload(bcs)\n"
                "bcs.show()",
    ),
    dict(
        label="Select Joints",
        annotation="Select all joints under the selected group(s)",
        icon="select_joints.png",
        source="python",
        command="import bc_select_bones_under as bcb\n"
                "from importlib import reload; reload(bcb)\n"
                "bcb.select_bones_under_selection()",
    ),
    dict(
        label="Namespaces",
        annotation="Strip namespaces from current scene (destructive)",
        icon="namespace.png",
        source="python",
        command="import bc_namespace_flatten as bcnf\n"
                "from importlib import reload; reload(bcnf)\n"
                "bcnf.show()",
    ),
]


def mel_escape(value):
    """Escape a Python string for use inside a MEL double-quoted literal."""
    return (value.replace("\\", "\\\\")
                 .replace('"', '\\"')
                 .replace("\n", "\\n")
                 .replace("\t", "\\t"))


def emit_button(b):
    lines = [
        "    shelfButton",
        "        -enableCommandRepeat 1",
        "        -enable 1",
        "        -width 35",
        "        -height 34",
        "        -manage 1",
        "        -visible 1",
        "        -preventOverride 0",
        '        -annotation "%s"' % mel_escape(b["annotation"]),
        '        -label "%s"' % mel_escape(b["label"]),
        "        -labelOffset 0",
        "        -rotation 0",
        "        -flipX 0",
        "        -flipY 0",
        "        -useAlpha 1",
        '        -font "plainLabelFont"',
        '        -image "%s"' % b["icon"],
        '        -image1 "%s"' % b["icon"],
        '        -style "iconOnly"',
        "        -marginWidth 0",
        "        -marginHeight 1",
        '        -command "%s"' % mel_escape(b["command"]),
        '        -sourceType "%s"' % b["source"],
        "        -commandRepeatable 1",
        "        -flat 1",
    ]
    if b.get("overlay"):
        lines.insert(-1, '        -imageOverlayLabel "%s"' % b["overlay"])
    lines.append("    ;")
    return "\n".join(lines)


def build():
    out = [
        "// shelf_%s.mel - GENERATED by build_shelf.py, do not edit by hand." % SHELF_NAME,
        "// Editing the shelf inside Maya writes to your prefs, not to this repo.",
        "// Change the BUTTONS table in build_shelf.py and re-run it instead.",
        "",
        "global proc shelf_%s () {" % SHELF_NAME,
        "    global string $gBuffStr;",
        "    global string $gBuffStr0;",
        "    global string $gBuffStr1;",
        "",
    ]
    out.extend(emit_button(b) for b in BUTTONS)
    out.append("}")
    out.append("")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out))
    return OUT


if __name__ == "__main__":
    path = build()
    print("wrote %s" % path)
    print("%d buttons" % len(BUTTONS))
    for b in BUTTONS:
        print("   %-16s %-22s %s" % (b["label"], b["icon"], b["source"]))
