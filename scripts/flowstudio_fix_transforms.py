"""Find and fix the transformed geometry that Flow Studio's GEO check rejects.

Flow Studio compares each mesh transform's local matrix against the identity matrix
EXACTLY, with ==. So there are two very different reasons a mesh gets flagged:

  * it is genuinely moved/rotated/scaled, or
  * it is visually at origin but a hair off in floating point (1e-8), usually from a
    past freeze, an import, or a scale of 0.9999999997.

The second kind needs nothing but the values re-set cleanly. The first kind, on a skinned
mesh, needs the skin detached, the transform frozen and the skin rebound - which is why
the validator's own message says so.

    import flowstudio_fix_transforms as fx
    fx.report()        # what is wrong, and which kind
    fx.fix()           # dry run - says what it would do
    fx.fix(apply=True) # actually do it
"""

import maya.cmds as cmds

IDENTITY = [1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0]

# Anything within this of identity is float noise, not a real transform.
EPSILON = 1e-5


def _geo_group():
    groups = cmds.ls("GEO") or []
    return groups[0] if len(groups) == 1 else None


def _mesh_transforms(geo):
    meshes = cmds.listRelatives(geo, allDescendents=True, path=True, type="mesh") or []
    return sorted(set(cmds.listRelatives(meshes, parent=True, path=True) or []))


def _offenders(geo):
    """Returns [(transform, matrix, max_deviation, skin_clusters)] for flagged meshes."""
    out = []
    for node in _mesh_transforms(geo):
        matrix = cmds.xform(node, query=True, matrix=True, objectSpace=True)
        if matrix == IDENTITY:
            continue
        deviation = max(abs(a - b) for a, b in zip(matrix, IDENTITY))
        shapes = cmds.listRelatives(node, shapes=True, noIntermediate=True, path=True) or []
        skins = []
        for shape in shapes:
            skins.extend(cmds.listConnections(shape, type="skinCluster") or [])
        out.append((node, matrix, deviation, sorted(set(skins))))
    return out


def report():
    """Print every mesh Flow Studio would flag, and why."""
    geo = _geo_group()
    if not geo:
        print("No single node named 'GEO' found - fix that first.")
        return []

    offenders = _offenders(geo)
    if not offenders:
        print("No transformed geometry under %r. This check should pass." % geo)
        return []

    print("Flow Studio compares each mesh's local matrix to identity with ==, so any")
    print("deviation at all fails. Found %d:\n" % len(offenders))
    for node, _matrix, deviation, skins in offenders:
        kind = "float noise" if deviation < EPSILON else "REAL transform"
        print("  %s" % node)
        print("     t=%s" % [round(v, 6) for v in cmds.xform(node, q=True, t=True, os=True)])
        print("     r=%s" % [round(v, 6) for v in cmds.xform(node, q=True, ro=True, os=True)])
        print("     s=%s" % [round(v, 6) for v in cmds.xform(node, q=True, s=True, os=True, r=True)])
        print("     largest deviation from identity: %.3e  -> %s" % (deviation, kind))
        print("     skinCluster: %s" % (", ".join(skins) if skins else "none (not skinned)"))
        print("")
    return offenders


def _snap_to_identity(node):
    """Re-set the transform channels to exact zeros/ones. Only safe for float noise.

    Binding a skin LOCKS the mesh's transform channels, so a skinned mesh has to be
    temporarily unlocked. That is fine here precisely because this only ever runs on
    deviations below EPSILON - the geometry does not visibly move, and the skinCluster's
    bindPreMatrix is unaffected at that magnitude. Locks are restored either way.

    Returns:
        bool: False if a channel is driven by a connection, which must not be overwritten.
    """
    plugs = ["%s.%s%s" % (node, attr, axis)
             for attr, _v in (("translate", 0.0), ("rotate", 0.0), ("scale", 1.0))
             for axis in "XYZ"]

    # A connected channel is driven by something else - never clobber it.
    for plug in plugs:
        if cmds.listConnections(plug, source=True, destination=False):
            return False

    relock = [p for p in plugs if cmds.getAttr(p, lock=True)]
    try:
        for plug in relock:
            cmds.setAttr(plug, lock=False)
        for attr, value in (("translate", 0.0), ("rotate", 0.0), ("scale", 1.0)):
            for axis in "XYZ":
                cmds.setAttr("%s.%s%s" % (node, attr, axis), value)
    finally:
        for plug in relock:
            cmds.setAttr(plug, lock=True)
    return True


def fix(apply=False):
    """Fix what can be fixed safely; report what needs manual work.

    Args:
        apply (bool): False (default) only says what it would do.

    Returns:
        dict: {'snapped': [...], 'needs_reskin': [...], 'blocked': [...]}
    """
    geo = _geo_group()
    if not geo:
        print("No single node named 'GEO' found - fix that first.")
        return {}

    result = {"snapped": [], "needs_reskin": [], "needs_freeze": [], "blocked": []}
    offenders = _offenders(geo)

    if apply:
        cmds.undoInfo(openChunk=True)
    try:
        for node, _matrix, deviation, skins in offenders:
            if deviation >= EPSILON:
                # A real transform. Freezing a skinned mesh silently breaks the bind,
                # so that case is never handled automatically.
                result["needs_reskin" if skins else "needs_freeze"].append(node)
                continue
            if not apply:
                result["snapped"].append(node)
                continue
            if _snap_to_identity(node):
                result["snapped"].append(node)
            else:
                result["blocked"].append(node)
    finally:
        if apply:
            cmds.undoInfo(closeChunk=True)

    verb = "Snapped" if apply else "Would snap"
    if result["snapped"]:
        print("%s to exact identity (float noise only, geometry does not move):" % verb)
        for node in result["snapped"]:
            print("   %s" % node)
    if result["needs_reskin"]:
        print("\nGenuinely transformed AND skinned - needs manual work:")
        for node in result["needs_reskin"]:
            print("   %s" % node)
        print("   Duplicate the mesh first (to keep the weights), then Skin > Unbind Skin,")
        print("   Modify > Freeze Transformations, re-bind, and Skin > Copy Skin Weights")
        print("   from the duplicate.")
    if result["needs_freeze"]:
        print("\nGenuinely transformed, not skinned - just freeze them:")
        for node in result["needs_freeze"]:
            print("   %s   (Modify > Freeze Transformations)" % node)
    if result["blocked"]:
        print("\nCould not touch - a transform channel is driven by a connection:")
        for node in result["blocked"]:
            print("   %s   (check its incoming connections / constraints)" % node)

    if apply and result["snapped"]:
        remaining = _offenders(geo)
        print("\nRe-checked: %d mesh(es) still flagged." % len(remaining))
    elif not apply:
        print("\nDry run. Call fix(apply=True) to perform the snaps above.")
    return result


if __name__ == "__main__":
    report()
