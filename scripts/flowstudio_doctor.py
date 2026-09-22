"""Report exactly why Flow Studio's GEO and rig checks are failing on the current scene.

The validator prints one failure and stops, so a scene with several problems takes
several runs to untangle. This checks every condition those two checks apply and prints
all of them at once, in the order the validator evaluates them.

Paste into Maya's Script Editor (Python tab):

    import flowstudio_doctor
    flowstudio_doctor.check()
"""

import maya.cmds as cmds

IDENTITY = [1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0]


def _line(ok, label, detail=""):
    print("  [%s] %-52s %s" % ("PASS" if ok else "FAIL", label, detail))
    return ok


def _fmt(nodes, limit=6):
    nodes = list(nodes)
    shown = ", ".join(nodes[:limit])
    return shown + (" ... (+%d more)" % (len(nodes) - limit) if len(nodes) > limit else "")


def check_geo():
    print("\n=== GEO group ===")
    groups = cmds.ls("GEO") or []
    if not _line(bool(groups), "a node named exactly 'GEO' exists",
                 "found none - group your meshes under one called GEO" if not groups else ""):
        return False
    if not _line(len(groups) == 1, "exactly one GEO group", _fmt(groups) if len(groups) > 1 else ""):
        return False

    geo = groups[0]
    local = cmds.xform(geo, q=True, m=True, os=True)
    if not _line(local == IDENTITY, "GEO itself has no transform",
                 "zero its translate/rotate, set scale to 1" if local != IDENTITY else ""):
        return False

    world = cmds.xform(geo, q=True, m=True, ws=True)
    parent = (cmds.listRelatives(geo, parent=True, path=True) or ["(world)"])[0]
    if not _line(world == IDENTITY, "GEO's parent has no transform",
                 "parent is %s" % parent if world != IDENTITY else ""):
        return False

    meshes = cmds.listRelatives(geo, allDescendents=True, path=True, type="mesh") or []
    transforms = list(set(cmds.listRelatives(meshes, parent=True, path=True) or []))
    bad = [t for t in transforms
           if cmds.xform(t, q=True, matrix=True, objectSpace=True) != IDENTITY]
    # This is the one that usually bites: a skinned mesh cannot simply be frozen.
    if not _line(not bad, "no geometry under GEO is transformed",
                 _fmt(bad) if bad else ""):
        print("        These need translate/rotate zeroed and scale 1. For a skinned mesh")
        print("        that means detach skin -> freeze transformations -> re-bind.")
        return False

    from wd_validator import utilities
    curves = utilities.get_animation_curves_connected_to_group(geo)
    if not _line(not curves, "no animation curves on GEO or its history",
                 _fmt(curves) if curves else ""):
        return False

    contents = cmds.listRelatives(geo, allDescendents=True) or []
    if not _line(bool(contents), "GEO is not empty"):
        return False

    print("  -> GEO check should PASS")
    return True


def check_rig():
    print("\n=== rig ===")
    joints = cmds.ls(type="joint") or []
    if not _line(bool(joints), "scene contains joints"):
        return False

    # the validator finds the root by walking up from a joint skinning a mesh under GEO
    geo = (cmds.ls("GEO") or [None])[0]
    shapes = cmds.listRelatives(geo, allDescendents=True, noIntermediate=True,
                                type="shape", fullPath=True) or [] if geo else []
    root = None
    skinned = False
    for shape in shapes:
        clusters = cmds.listConnections(shape, type="skinCluster")
        if not clusters:
            continue
        skinned = True
        bound = cmds.listConnections(clusters[0], type="joint")
        if not bound:
            continue
        root = bound[0]
        while True:
            parent = cmds.listRelatives(root, parent=True, type="joint")
            if not parent:
                break
            root = parent[0]
        break

    if not _line(skinned, "a mesh under GEO has a skinCluster",
                 "nothing under GEO is skinned" if not skinned else ""):
        return False
    if not _line(bool(root), "root joint resolved from that skinCluster", root or ""):
        return False

    roots = [j for j in joints if not (cmds.listRelatives(j, parent=True, type="joint") or [])]
    if not _line(len(roots) == 1, "exactly one root joint in the scene",
                 "found %d: %s" % (len(roots), _fmt(roots)) if len(roots) != 1 else root):
        return False

    parent = (cmds.listRelatives(root, parent=True, path=True) or [None])[0]
    body = parent and parent.split("|")[-1].endswith("_BODY")
    _line(bool(body), "root joint is directly under a *_BODY group",
          "parent is %s" % (parent or "(world)") if not body else parent)

    print("  -> root joint is %r" % root)
    return True


def check():
    print("=" * 72)
    print("Flow Studio scene doctor - every condition the GEO and rig checks apply")
    print("=" * 72)
    geo_ok = check_geo()
    rig_ok = check_rig()
    print("\nGEO: %s   RIG: %s" % ("ok" if geo_ok else "blocked",
                                   "ok" if rig_ok else "blocked"))
    print("Fix the first FAIL in each section, then re-run the validator.")
    return geo_ok, rig_ok


if __name__ == "__main__":
    check()
