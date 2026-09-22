"""Remove the objects that make Flow Studio reject an upload with
"Objects(s) with bone parents are not supported".

Two ways to use it, depending on where you want to fix it.

1. In the open Maya scene, then export through the validator as usual:

       import flowstudio_strip_bone_parents as sbp
       sbp.fix_scene()               # dry run
       sbp.fix_scene(apply=True)

   This UNPARENTS rather than deletes. On a rig like the sniper3d one, the foot
   pivot locators carry message connections to the leg MetaNodes - the rig builder's
   record of where the heel and bank pivots are. Unparenting keeps those (message
   connections ignore hierarchy); deleting would break them.

2. Straight on an already-exported character.fbx, skipping the validator entirely:

       sbp.patch_fbx(r"D:/.../flow_studio_character_data/character.fbx")

   Here it DELETES them, which is safe: an FBX has no MetaNodes - message connections
   are not exported - so nothing references them any more. The original is kept
   alongside as character_before_strip.fbx, and metadata.json is untouched because it never
   mentioned these objects.
"""

import os
import shutil

import maya.cmds as cmds
import maya.mel as mel

# Node types that sit under joints but never reach the FBX, so are not the problem.
NON_EXPORTING = (
    "parentConstraint", "scaleConstraint", "orientConstraint", "pointConstraint",
    "aimConstraint", "poleVectorConstraint", "tangentConstraint", "normalConstraint",
    "geometryConstraint", "ikEffector",
)


def find(verbose=True):
    """Returns the DAG objects parented under joints that would reach the FBX."""
    blocking = []
    for joint in cmds.ls(type="joint", long=True) or []:
        for child in cmds.listRelatives(joint, children=True, fullPath=True) or []:
            if cmds.nodeType(child) == "joint" or cmds.nodeType(child) in NON_EXPORTING:
                continue
            blocking.append(child)
    if verbose:
        if blocking:
            print("Objects parented to a bone (%d):" % len(blocking))
            for node in blocking:
                shapes = cmds.listRelatives(node, shapes=True) or []
                kinds = sorted({cmds.nodeType(s) for s in shapes}) or ["no shape"]
                print("   %-28s %s" % (node.split("|")[-1], ", ".join(kinds)))
        else:
            print("No objects are parented under joints.")
    return blocking


def fix_scene(apply=False, destination=None):
    """Unparent bone-parented objects in the CURRENT scene.

    Args:
        apply (bool): False (default) only reports.
        destination (str): where to move them. Defaults to 'Rig_Grp' if it exists,
            otherwise the world.

    Returns:
        list[str]: the objects moved (or that would be).
    """
    blocking = find(verbose=False)
    if not blocking:
        print("Nothing parented under a joint - this is not what the upload is rejecting.")
        return []

    if destination is None:
        destination = "Rig_Grp" if cmds.objExists("Rig_Grp") else None

    where = destination if destination else "the world"
    if not apply:
        print("Would move %d object(s) out of the skeleton, to %s:" % (len(blocking), where))
        for node in blocking:
            print("   %s" % node.split("|")[-1])
        print("\nDry run. Call fix_scene(apply=True) to do it.")
        return blocking

    moved = []
    cmds.undoInfo(openChunk=True)
    try:
        for node in blocking:
            # world position is preserved, and message connections are unaffected
            new = cmds.parent(node, destination) if destination else cmds.parent(node, world=True)
            moved.append(new[0])
            print("   moved %-28s -> %s" % (node.split("|")[-1], where))
    finally:
        cmds.undoInfo(closeChunk=True)

    remaining = find(verbose=False)
    print("\nMoved %d. Still parented under joints: %d" % (len(moved), len(remaining)))
    print("Now re-run the validation and export again.")
    return moved


def patch_fbx(fbx_path, backup=True):
    """Strip bone-parented objects straight out of an exported FBX.

    Opens a NEW scene, so anything unsaved in the current one is lost - save first.

    Args:
        fbx_path (str): path to character.fbx.
        backup (bool): keep the original as <name>.bak. Defaults to True.

    Returns:
        list[str]: the objects removed.
    """
    fbx_path = fbx_path.replace("\\", "/")
    if not os.path.isfile(fbx_path):
        raise IOError("No such file: %s" % fbx_path)

    cmds.file(new=True, force=True)
    cmds.loadPlugin("fbxmaya", quiet=True)
    mel.eval('FBXImport -f "%s"' % fbx_path)

    blocking = find(verbose=True)
    if not blocking:
        print("\nNothing to strip - this FBX has no bone-parented objects.")
        return []

    names = [n.split("|")[-1] for n in blocking]
    cmds.delete(blocking)
    print("\nDeleted %d object(s) from the imported scene." % len(names))

    if backup:
        # NOT "<name>.fbx.bak": Maya's FBX exporter uses that suffix for its own
        # backup of the target and DELETES it on a successful export, so a backup
        # written there silently disappears. Verified in Maya 2027.
        root, ext = os.path.splitext(fbx_path)
        bak = root + "_before_strip" + ext
        if not os.path.isfile(bak):
            shutil.copy2(fbx_path, bak)
            print("Original kept as %s" % bak)

    mel.eval("FBXResetExport")
    mel.eval("FBXExportFileVersion -v FBX202000")
    mel.eval("FBXExportInAscii -v false")
    mel.eval('FBXExport -f "%s"' % fbx_path)
    print("Re-exported %s" % fbx_path)
    print("metadata.json is unchanged - it never referenced these objects.")
    return names


if __name__ == "__main__":
    find()
