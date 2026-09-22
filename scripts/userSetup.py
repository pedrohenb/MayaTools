"""MayaTools startup hook.

Maya runs every userSetup.py it finds on the script path, so this coexists with the
studio's own hook in modules/wlstools/scripts/userSetup.py rather than replacing it.

Two jobs:

1. Repair Maya's shelf preferences. The studio pipeline on P:
   (python/pipeline/startup.py -> loadShelf) deletes each of its shelf UI layouts and
   re-adds them with loadNewShelf on every launch. That appends a fresh
   shelfName<N>/shelfFile<N> optionVar without removing the stale one, and moves the
   re-added tab to the end of the tab strip. Maya's numbered shelf list then no longer
   lines up with the tab strip, and clicking a tab loads the wrong shelf - or nothing,
   which is why the FlowStudio tab came up empty. Those P: files are read-only under
   Perforce, so this repairs the result locally instead of changing the studio's copy.

2. Teach Flow Studio's "Auto Assign Bones" about Wildlife rig naming, so it stops
   saying "Could not guess template from Hip bone".

Both steps are idempotent and fail quietly - a broken startup hook is worse than a
missing feature.
"""

import maya.cmds as cmds
import maya.utils


def _repair_shelves():
    try:
        import fix_shelf_prefs
        result = fix_shelf_prefs.repair_shelf_prefs(verbose=False)
    except Exception as exc:
        print("[MayaTools] Shelf repair skipped: %s" % exc)
        return

    if not result:
        return

    dupes = len(result.get("duplicates") or [])
    filled = result.get("filled") or []
    if dupes or filled:
        print("[MayaTools] Shelf prefs repaired - %d duplicate(s) removed, populated: %s"
              % (dupes, ", ".join(filled) if filled else "none"))


def _register_rig_templates():
    try:
        import wd_flowstudio_templates
        wd_flowstudio_templates.register()
    except Exception as exc:
        print("[MayaTools] Rig template registration skipped: %s" % exc)


def _run():
    _repair_shelves()

    # DISABLED while wd-maya-tools is being tested as shipped.
    #
    # _register_rig_templates() appends Wildlife rig naming to Flow Studio's
    # retargeting templates at runtime, which makes "Auto Assign Bones" fill in
    # Zooba rigs. It is off so that a validation/export run exercises stock Flow
    # Studio behaviour and nothing here can be blamed for a failure.
    #
    # Re-enable by uncommenting the line below, or for one session only:
    #     import wd_flowstudio_templates; wd_flowstudio_templates.register()
    #
    # _register_rig_templates()


def _deferred():
    # lowestPriority puts this behind the studio's own
    # cmds.evalDeferred("startup.init(...)"), so it runs after the shelves have been
    # rebuilt and reordered rather than before.
    cmds.evalDeferred(_run, lowestPriority=True)


maya.utils.executeDeferred(_deferred)
