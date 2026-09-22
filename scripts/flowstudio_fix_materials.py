"""Convert unsupported materials to a type Flow Studio accepts.

Flow Studio only reads aiStandardSurface, standardSurface and aiFlat (see
wd_validator/static.py material_attributes). Anything else - lambert, blinn, phong -
fails the materials check.

This replaces each unsupported shader with a standardSurface, carries over the colour,
transparency and any incoming texture connections, and reassigns the same shading group,
so the assignment to geometry is preserved.

    import flowstudio_fix_materials as fm
    fm.report()          # what would change
    fm.convert()         # dry run
    fm.convert(apply=True)

The original shaders are left in the scene, disconnected, so the change can be inspected
or undone. Delete them with Edit > Delete Unused Nodes once you are happy.
"""

import maya.cmds as cmds

SUPPORTED = ("aiStandardSurface", "standardSurface", "aiFlat")

# Attributes worth carrying across, as {source_attr: standardSurface_attr}. Value and
# any incoming connection are both transferred.
CARRY = {
    "color": "baseColor",
    "diffuse": "base",
    "transparency": None,     # handled separately - standardSurface inverts it
    "incandescence": "emissionColor",
    "normalCamera": "normalCamera",
}


def _materials_on_geo():
    """Every shader assigned to geometry under GEO."""
    groups = cmds.ls("GEO") or []
    if not groups:
        return []
    shapes = cmds.listRelatives(groups, allDescendents=True, type="mesh",
                                noIntermediate=True, path=True) or []
    shaders = []
    for engine in set(cmds.listConnections(shapes, type="shadingEngine") or []):
        for shader in cmds.ls(cmds.listConnections(engine + ".surfaceShader"), materials=True) or []:
            shaders.append((shader, engine))
    return sorted(set(shaders))


def report():
    """List the shaders Flow Studio will reject."""
    found = _materials_on_geo()
    if not found:
        print("No shaders found on geometry under 'GEO'.")
        return []

    bad = [(s, e) for s, e in found if cmds.nodeType(s) not in SUPPORTED]
    print("Shaders on GEO geometry: %d   unsupported: %d" % (len(found), len(bad)))
    print("Flow Studio accepts: %s\n" % ", ".join(SUPPORTED))
    for shader, engine in found:
        node_type = cmds.nodeType(shader)
        mark = "  " if node_type in SUPPORTED else "->"
        print("  %s %-24s %-20s %s" % (mark, shader, node_type,
                                       "OK" if node_type in SUPPORTED else "NOT SUPPORTED"))
    return bad


def _transfer(src, dst, src_attr, dst_attr):
    """Copy a value, or rewire an incoming connection, from src.attr to dst.attr."""
    src_plug = "%s.%s" % (src, src_attr)
    dst_plug = "%s.%s" % (dst, dst_attr)
    if not cmds.objExists(src_plug) or not cmds.objExists(dst_plug):
        return
    incoming = cmds.listConnections(src_plug, source=True, destination=False, plugs=True)
    if incoming:
        cmds.connectAttr(incoming[0], dst_plug, force=True)
        return
    try:
        value = cmds.getAttr(src_plug)
        if isinstance(value, list) and value and isinstance(value[0], tuple):
            cmds.setAttr(dst_plug, *value[0], type="double3")
        else:
            cmds.setAttr(dst_plug, value)
    except Exception:
        pass


def convert(apply=False, target="standardSurface"):
    """Replace unsupported shaders with `target`, preserving assignment.

    Args:
        apply (bool): False (default) only reports.
        target (str): the shader type to create. Must be one Flow Studio supports.

    Returns:
        list[tuple]: (old_shader, new_shader) pairs.
    """
    if target not in SUPPORTED:
        raise ValueError("target must be one of %s" % (SUPPORTED,))

    bad = [(s, e) for s, e in _materials_on_geo() if cmds.nodeType(s) not in SUPPORTED]
    if not bad:
        print("Nothing to convert - every shader on GEO geometry is already supported.")
        return []

    if not apply:
        print("Would convert %d shader(s) to %s:" % (len(bad), target))
        for shader, _engine in bad:
            print("   %-24s %s -> %s" % (shader, cmds.nodeType(shader), target))
        print("\nDry run. Call convert(apply=True) to do it.")
        return []

    made = []
    cmds.undoInfo(openChunk=True)
    try:
        for shader, engine in bad:
            new = cmds.shadingNode(target, asShader=True, name=shader + "_" + target)
            for src_attr, dst_attr in CARRY.items():
                if dst_attr:
                    _transfer(shader, new, src_attr, dst_attr)
            # standardSurface has no transparency: it uses transmission instead, and
            # lambert transparency is inverted relative to opacity.
            tp = "%s.transparency" % shader
            if cmds.objExists(tp):
                try:
                    value = cmds.getAttr(tp)[0]
                    if any(v > 0.001 for v in value):
                        cmds.setAttr(new + ".transmission", sum(value) / 3.0)
                except Exception:
                    pass
            cmds.connectAttr(new + ".outColor", engine + ".surfaceShader", force=True)
            made.append((shader, new))
            print("   %-24s -> %s" % (shader, new))
    finally:
        cmds.undoInfo(closeChunk=True)

    print("\nConverted %d shader(s). The originals are still in the scene, disconnected." % len(made))
    print("Re-run the validation; then Edit > Delete Unused Nodes to clear the old ones.")
    return made


if __name__ == "__main__":
    report()
