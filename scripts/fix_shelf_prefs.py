"""Repair Maya's shelf preferences when shelf tabs appear but stay empty.

Cause: Maya's shelfTabChange() passes the *UI tab position* to loadShelf(),
which then looks the shelf up by that number in the shelfName<N>/shelfFile<N>
optionVars:

    string $shelfName = `optionVar -q ("shelfName" + $index)`;
    if ( `shelfLayout -exists $shelfName`
         && `shelfLayout -query -numberOfChildren $shelfName` == 0 )

So the optionVar table has to line up positionally with the tab strip. Two
things break that alignment:

  * duplicate entries in the optionVars - buildShelves() skips duplicate names
    when it creates the tabs, so every tab after the first duplicate sits at a
    lower UI position than its optionVar index;
  * shelves deleted and re-added at runtime (a startup script doing deleteUI +
    loadNewShelf) - the tab moves to the end of the strip while its optionVar
    entry stays put, or a fresh entry is appended and the stale one is left
    behind.

When the lookup lands on a shelf that already has buttons, the "only fill if
empty" guard fails and loadShelf() returns having done nothing, so the tab you
clicked is never populated.

Fix: rewrite the optionVar table in the order the tabs actually appear in the
UI, so index N always describes tab N.

Paste into Maya's Script Editor (Python tab) and run.
"""

import maya.cmds as cmds
import maya.mel as mel

KEYS = ("shelfName", "shelfFile", "shelfAlign", "shelfLoad", "shelfVersion")


def _read_table():
    """Existing optionVar rows, keyed by shelf name (first occurrence wins)."""
    n = cmds.optionVar(query="numShelves") or 0
    table, order, dupes = {}, [], []
    for i in range(1, n + 1):
        name = cmds.optionVar(query="shelfName%d" % i)
        if not name:
            continue
        if name in table:
            dupes.append((i, name))
            continue
        order.append(name)
        table[name] = {
            "shelfFile": cmds.optionVar(query="shelfFile%d" % i) or ("shelf_" + name),
            "shelfAlign": cmds.optionVar(query="shelfAlign%d" % i) or "left",
            "shelfLoad": int(bool(cmds.optionVar(query="shelfLoad%d" % i))),
            "shelfVersion": cmds.optionVar(query="shelfVersion%d" % i) or "",
        }
    return n, table, order, dupes


def repair_shelf_prefs(verbose=True):
    top = mel.eval("global string $gShelfTopLevel; $tmp = $gShelfTopLevel;")
    tabs = cmds.shelfTabLayout(top, query=True, childArray=True) or []
    if not tabs:
        print("No shelf tabs found - is the shelf hidden?")
        return None

    old_n, table, old_order, dupes = _read_table()

    # The tab strip is the source of truth. Anything in the prefs that has no
    # tab is kept, appended after the live ones, so nothing is silently lost.
    orphans = [name for name in old_order if name not in tabs]
    final = list(tabs) + orphans

    misaligned = [(i, name, old_order[i - 1] if i <= len(old_order) else None)
                  for i, name in enumerate(tabs, 1)
                  if i > len(old_order) or old_order[i - 1] != name]

    if verbose:
        print("Tabs in UI: %d | prefs entries: %d | duplicates: %d | orphans: %d"
              % (len(tabs), old_n, len(dupes), len(orphans)))
        if dupes:
            print("  duplicates dropped: %s"
                  % ", ".join("#%d %s" % d for d in dupes))
        if orphans:
            print("  prefs entries with no tab (kept at the end): %s"
                  % ", ".join(orphans))
        if misaligned:
            print("  misaligned tabs (position -> was pointing at):")
            for i, name, was in misaligned[:12]:
                print("    tab %-3d %-22s -> %s" % (i, name, was))
            if len(misaligned) > 12:
                print("    ... and %d more" % (len(misaligned) - 12))
        else:
            print("  tab order already matches the prefs order.")

    # Clear every old slot, then write the table back in live tab order.
    for i in range(1, max(old_n, len(final)) + 1):
        for key in KEYS:
            var = "%s%d" % (key, i)
            if cmds.optionVar(exists=var):
                cmds.optionVar(remove=var)

    for j, name in enumerate(final, 1):
        row = table.get(name) or {
            "shelfFile": "shelf_" + name,
            "shelfAlign": "left",
            "shelfLoad": 1,
            "shelfVersion": "",
        }
        cmds.optionVar(stringValue=("shelfName%d" % j, name))
        cmds.optionVar(stringValue=("shelfFile%d" % j, row["shelfFile"]))
        cmds.optionVar(stringValue=("shelfAlign%d" % j, row["shelfAlign"]))
        cmds.optionVar(intValue=("shelfLoad%d" % j, row["shelfLoad"]))
        if row["shelfVersion"]:
            cmds.optionVar(stringValue=("shelfVersion%d" % j, row["shelfVersion"]))

    cmds.optionVar(intValue=("numShelves", len(final)))

    # Populate every tab that is still empty. Indices line up now, so each call
    # loads the shelf it names. Tabs that already have buttons are left alone.
    filled, failed = [], []
    for i, name in enumerate(tabs, 1):
        if cmds.shelfLayout(name, query=True, numberOfChildren=True):
            continue
        try:
            mel.eval("loadShelf(%d)" % i)
        except Exception as exc:
            failed.append("%s (%s)" % (name, exc))
            continue
        count = cmds.shelfLayout(name, query=True, numberOfChildren=True)
        if count:
            filled.append("%s:%d" % (name, count))

    cmds.savePrefs(general=True)

    if verbose:
        print("numShelves %d -> %d" % (old_n, len(final)))
        print("Populated: %s" % (", ".join(filled) if filled else "none"))
        if failed:
            print("Failed to load: %s" % ", ".join(failed))
        print("Preferences saved.")

    return {"tabs": len(tabs), "numShelves": len(final), "duplicates": dupes,
            "orphans": orphans, "filled": filled, "failed": failed}


if __name__ == "__main__":
    repair_shelf_prefs()
