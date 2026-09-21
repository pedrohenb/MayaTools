"""Teach Flow Studio's "Auto Assign Bones" about Wildlife rig naming.

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
DERIVED = {
    'zooba_game_art.json': {
        'LeftToeBase': 'L_Toe_JNT',
        'RightToeBase': 'R_Toe_JNT',
    },
}

# Snapshot of the studio mapping, used only when P: cannot be read (offline, VPN down).
# Regenerate by re-running the generator in the MayaTools repo.
FALLBACK = {
    'zooba_game_art.json': {
    'Hips':                    'Hips_JNT',
    'LeftUpLeg':               'L_Upper_Leg_JNT',
    'RightUpLeg':              'R_Upper_Leg_JNT',
    'Spine':                   'Spine0_JNT',
    'LeftLeg':                 'L_Lower_Leg_JNT',
    'RightLeg':                'R_Lower_Leg_JNT',
    'Spine1':                  'Spine1_JNT',
    'LeftFoot':                'L_Foot_JNT',
    'RightFoot':               'R_Foot_JNT',
    'Spine2':                  'Spine2_JNT',
    'LeftToeBase':             '',
    'RightToeBase':            '',
    'Neck':                    'Neck0_JNT',
    'LeftShoulder':            'L_Shoulder_JNT',
    'RightShoulder':           'R_Shoulder_JNT',
    'Head':                    'Head_JNT',
    'LeftArm':                 'L_Upper_Arm_JNT',
    'RightArm':                'R_Upper_Arm_JNT',
    'LeftForeArm':             'L_Lower_Arm_JNT',
    'RightForeArm':            'R_Lower_Arm_JNT',
    'LeftHand':                'L_Hand_JNT',
    'RightHand':               'R_Hand_JNT',
    'LeftHandIndex1':          'L_Index0_JNT',
    'LeftHandIndex2':          'L_Index1_JNT',
    'LeftHandIndex3':          'L_Index2_JNT',
    'LeftHandMiddle1':         'L_Ring0_JNT',
    'LeftHandMiddle2':         'L_Ring1_JNT',
    'LeftHandMiddle3':         'L_Ring2_JNT',
    'LeftHandPinky1':          'L_Middle0_JNT',
    'LeftHandPinky2':          'L_Middle1_JNT',
    'LeftHandPinky3':          'L_Middle2_JNT',
    'LeftHandRing1':           '',
    'LeftHandRing2':           '',
    'LeftHandRing3':           '',
    'LeftHandThumb1':          'L_Thumb0_JNT',
    'LeftHandThumb2':          'L_Thumb1_JNT',
    'LeftHandThumb3':          'L_Thumb2_JNT',
    'RightHandIndex1':         'R_Index0_JNT',
    'RightHandIndex2':         'R_Index1_JNT',
    'RightHandIndex3':         'R_Index2_JNT',
    'RightHandMiddle1':        'R_Ring0_JNT',
    'RightHandMiddle2':        'R_Ring1_JNT',
    'RightHandMiddle3':        'R_Ring2_JNT',
    'RightHandPinky1':         'R_Middle0_JNT',
    'RightHandPinky2':         'R_Middle1_JNT',
    'RightHandPinky3':         'R_Middle2_JNT',
    'RightHandRing1':          '',
    'RightHandRing2':          '',
    'RightHandRing3':          '',
    'RightHandThumb1':         'R_Thumb0_JNT',
    'RightHandThumb2':         'R_Thumb1_JNT',
    'RightHandThumb3':         'R_Thumb2_JNT',
    },
}


def _load_standard(filename):
    """Returns {flow_studio_slot: joint_name} for one studio rig standard."""
    path = os.path.join(STUDIO_STD_DIR, filename)
    try:
        with open(path, 'r') as handle:
            return json.load(handle).get('joint2joint', {}), 'P: drive'
    except Exception:
        return dict(FALLBACK.get(filename, {})), 'built-in snapshot'


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
            for slot, joint in DERIVED.get(filename, {}).items():
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
