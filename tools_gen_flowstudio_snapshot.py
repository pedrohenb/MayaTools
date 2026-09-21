"""Generate MayaTools/scripts/wd_flowstudio_templates.py with a baked-in snapshot
of the studio's Zooba rig standard (used as a fallback when P: is unreachable)."""
import json
import os
import sys

sys.path.insert(0, r"C:/Users/PedroHenb/Documents/maya/modules/wd-maya-tools/scripts")
from wd_validator import static

STD_DIR = (r"P:/tech_art/tools/maya/python/pipeline/animationRetarget/mkt/"
           r"hik_animation_transfer/1.3.0/python-2.7/hik_animation_transfer/"
           r"supported_rig_std")

zoo = json.load(open(os.path.join(STD_DIR, "zooba_game_art.json"), encoding="utf-8"))
j2j = zoo["joint2joint"]
slots = list(static.retargeting_templates.keys())

snapshot = {s: j2j.get(s, "") for s in slots}
body = "\n".join('    %-26s %s,' % ("'%s':" % s, repr(snapshot[s])) for s in slots)

OUT = r"D:/Projects/MayaTools/scripts/wd_flowstudio_templates.py"

TEMPLATE = '''"""Teach Flow Studio's "Auto Assign Bones" about Wildlife rig naming.

Flow Studio (wd-maya-tools) ships five naming conventions and works out which one a
scene uses by looking at the hip joint:

    retargeting_templates_names = ['Flow Studio', 'Unreal Engine', 'DAZ 3d',
                                   'Character Creator 4', 'Quick Rig']
    'Hips': ['Hips', 'pelvis', 'hip', 'CC_Base_Hip', 'QuickRigCharacter_Hips']

Wildlife rigs use none of those (Zooba hips are 'Hips_JNT'), so auto-assign gives up
with "Could not guess template from Hip bone" and fills in nothing.

This module appends extra columns to those tables at runtime, built from the studio's
own rig standards on P:. Because it patches at runtime and lives outside wd-maya-tools,
it survives a Flow Studio update - reinstalling their module does not wipe it.

Usage (normally called from userSetup.py):

    import wd_flowstudio_templates
    wd_flowstudio_templates.register()

It is safe to call more than once.
"""

import json
import os

STUDIO_STD_DIR = (
    r"P:/tech_art/tools/maya/python/pipeline/animationRetarget/mkt/"
    r"hik_animation_transfer/1.3.0/python-2.7/hik_animation_transfer/"
    r"supported_rig_std"
)

# Studio standards to expose, as (column name shown in the script editor, json file).
STANDARDS = [
    ('Zooba Game Art', 'zooba_game_art.json'),
]

# Slots the studio file does not map, filled in by inference rather than from their
# data. Kept separate so it is obvious what is ours and what is theirs.
#
# Zooba puts the toe on HIK's "ExtraFinger" slot (LeftFootExtraFinger1 -> L_Toe_JNT).
# Flow Studio has no such slot but does have LeftToeBase, and feet matter for
# retargeting, so route it there. Set USE_DERIVED = False to turn this off.
USE_DERIVED = True
DERIVED = {{
    'zooba_game_art.json': {{
        'LeftToeBase': 'L_Toe_JNT',
        'RightToeBase': 'R_Toe_JNT',
    }},
}}

# Snapshot of the studio mapping, used only when P: cannot be read (offline, VPN down).
# Regenerate by re-running the generator in the MayaTools repo.
FALLBACK = {{
    'zooba_game_art.json': {{
{body}
    }},
}}


def _load_standard(filename):
    """Returns {{flow_studio_slot: joint_name}} for one studio rig standard."""
    path = os.path.join(STUDIO_STD_DIR, filename)
    try:
        with open(path, 'r') as handle:
            return json.load(handle).get('joint2joint', {{}}), 'P: drive'
    except Exception:
        return dict(FALLBACK.get(filename, {{}})), 'built-in snapshot'


def register(verbose=True):
    """Appends the studio rig standards to Flow Studio's retargeting templates.

    Args:
        verbose (bool): print a short report. Defaults to True.

    Returns:
        list[str]: the column names that are now available.
    """
    try:
        from wd_validator import static
    except ImportError:
        if verbose:
            print('[MayaTools] wd-maya-tools not on the path; skipping rig templates.')
        return []

    templates = static.retargeting_templates
    names = static.retargeting_templates_names
    slots = list(templates.keys())
    added = []

    for column_name, filename in STANDARDS:
        if column_name in names:
            continue  # already registered this session

        mapping, source = _load_standard(filename)
        if USE_DERIVED:
            for slot, joint in DERIVED.get(filename, {{}}).items():
                mapping.setdefault(slot, joint)

        if not mapping.get('Hips'):
            # Without a hip name Flow Studio cannot identify the template at all.
            if verbose:
                print('[MayaTools] %s has no Hips entry; skipping.' % column_name)
            continue

        # Every slot list must stay the same length - the column index is what ties
        # a convention together. Unmapped slots get '' (never a real node name, and
        # still sortable, which eye_rotations_gui relies on).
        for slot in slots:
            templates[slot].append(mapping.get(slot, ''))
        names.append(column_name)

        filled = sum(1 for s in slots if mapping.get(s))
        added.append(column_name)
        if verbose:
            print('[MayaTools] Flow Studio: added "%s" from %s - %d/%d bones '
                  '(hip: %s)' % (column_name, source, filled, len(slots), mapping['Hips']))

    return names


def unmapped(column_name='Zooba Game Art'):
    """Returns the Flow Studio slots this standard leaves blank, for troubleshooting."""
    from wd_validator import static
    if column_name not in static.retargeting_templates_names:
        return []
    i = static.retargeting_templates_names.index(column_name)
    return [slot for slot, values in static.retargeting_templates.items()
            if i < len(values) and not values[i]]
'''

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(TEMPLATE.format(body=body))

print("wrote", OUT)
print("baked %d slots, %d with a joint" % (len(snapshot), sum(1 for v in snapshot.values() if v)))
