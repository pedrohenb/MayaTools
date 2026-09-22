"""Find the objects behind Flow Studio's "Objects(s) with bone parents are not supported".

That error comes from Flow Studio's SERVER, after upload - the local validator has no
such check, so a character can pass validation, export and still be rejected.

It means the FBX contains a DAG object whose parent is a joint. Flow Studio wants the
skeleton to contain nothing but joints; geometry belongs under GEO, bound with a
skinCluster, not parented to a bone.

Constraint nodes sitting under joints look like the same thing in the outliner but are
NOT the cause: Maya's FBX exporter has FBXExportConstraints off by default, so they never
reach the file. Verified by exporting an ASCII FBX and reading it. They are listed
separately below so they can be ruled out at a glance.

    import flowstudio_find_bone_parents as bp
    bp.report()
"""

import maya.cmds as cmds

# Node types that live under joints but never reach the FBX.
NON_EXPORTING = (
    "parentConstraint", "scaleConstraint", "orientConstraint", "pointConstraint",
    "aimConstraint", "poleVectorConstraint", "tangentConstraint", "normalConstraint",
    "geometryConstraint", "ikEffector",
)


def _children_of_joints():
    """Returns [(joint, child, node_type, shape_types)] for every non-joint child."""
    found = []
    for joint in cmds.ls(type="joint", long=True) or []:
        for child in cmds.listRelatives(joint, children=True, fullPath=True) or []:
            node_type = cmds.nodeType(child)
            if node_type == "joint":
                continue
            shapes = cmds.listRelatives(child, shapes=True, fullPath=True) or []
            shape_types = sorted({cmds.nodeType(s) for s in shapes})
            found.append((joint, child, node_type, shape_types))
    return found


def report():
    """Print what would trip the server-side check, and what is harmless."""
    found = _children_of_joints()
    if not found:
        print("No objects are parented under joints. This is not what the upload is")
        print("rejecting - re-check the FBX contents.")
        return {"blocking": [], "harmless": []}

    blocking, harmless = [], []
    for joint, child, node_type, shape_types in found:
        (harmless if node_type in NON_EXPORTING else blocking).append(
            (joint, child, node_type, shape_types))

    if blocking:
        print("THESE are what Flow Studio is rejecting - objects parented to a bone:\n")
        for joint, child, node_type, shape_types in blocking:
            print("   %s" % child.split("|")[-1])
            print("      parent joint : %s" % joint.split("|")[-1])
            print("      node type    : %s%s" % (node_type,
                                                 "  shapes: %s" % ", ".join(shape_types)
                                                 if shape_types else ""))
            print("      full path    : %s" % child)
            if "mesh" in shape_types:
                print("      -> geometry: move it under GEO and bind it to the joint with a")
                print("         skinCluster instead of parenting it.")
            elif not shape_types:
                print("      -> an empty group/null: delete it, or move it out of the skeleton.")
            else:
                print("      -> move it out of the skeleton; constrain it to the joint if it")
                print("         has to follow the bone.")
            print("")
    else:
        print("Nothing under a joint would reach the FBX.\n")

    if harmless:
        print("Under joints but NOT exported, so not the cause (FBXExportConstraints is off):")
        for joint, child, node_type, _shapes in harmless:
            print("   %-34s %-20s under %s" % (child.split("|")[-1], node_type,
                                               joint.split("|")[-1]))

    print("\n%d blocking, %d harmless." % (len(blocking), len(harmless)))
    return {"blocking": blocking, "harmless": harmless}


def select_blocking():
    """Select the offending objects so they can be dealt with in the outliner."""
    result = report()
    nodes = [child for _j, child, _t, _s in result["blocking"]]
    if nodes:
        cmds.select(nodes, replace=True)
        print("\nSelected %d object(s)." % len(nodes))
    else:
        cmds.select(clear=True)
    return nodes


if __name__ == "__main__":
    report()
