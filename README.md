# MayaTools

Personal Maya tooling, packaged as a Maya module so it works across Maya versions
without reinstalling anything when you upgrade.

## Install

Clone anywhere, then drop a `.mod` file into your Maya modules folder
(`~/Documents/maya/modules/MayaTools.mod`) pointing at the clone:

```
+ MayaTools 1.0.0 D:/Projects/MayaTools
scripts: scripts
icons: icons
MAYA_SHELF_PATH +:= shelves
```

That single file covers every Maya version — there is nothing under `maya/2027/`,
`maya/2028/` and so on to keep in sync.

To update: `git pull`. Restart Maya.

## Layout

| path       | what it holds                                              |
|------------|------------------------------------------------------------|
| `scripts/` | Python modules, on Maya's `sys.path` automatically          |
| `icons/`   | Shelf icons — the source of truth, on `XBMLANGPATH`         |
| `shelves/` | Shelf definitions, picked up via `MAYA_SHELF_PATH`          |

## What runs at startup

`scripts/userSetup.py` runs two things, both deferred until after the studio's own
startup hook, both idempotent, both failing quietly rather than breaking Maya.

### 1. Shelf preference repair (`fix_shelf_prefs.py`)

The studio pipeline on `P:` (`python/pipeline/startup.py` → `loadShelf`) deletes each
of its shelf UI layouts and re-adds them with `loadNewShelf` on every launch. That
appends a fresh `shelfName<N>` / `shelfFile<N>` optionVar without removing the stale
one, and moves the re-added tab to the end of the tab strip.

Maya's `shelfTabChange()` passes the *UI tab position* to `loadShelf()`, which looks
the shelf up by that number in the optionVars. Once the two lists drift apart, clicking
a tab loads the wrong shelf — or nothing, which is what left the FlowStudio tab empty.

The P: files are read-only under Perforce, so this repairs the result locally rather
than changing the studio's copy. Run it by hand any time with:

```python
import fix_shelf_prefs
fix_shelf_prefs.repair_shelf_prefs()
```

### 2. Flow Studio rig templates (`wd_flowstudio_templates.py`)

Flow Studio's "Auto Assign Bones" ships five naming conventions and identifies which
one a scene uses from the hip joint:

```python
'Hips': ['Hips', 'pelvis', 'hip', 'CC_Base_Hip', 'QuickRigCharacter_Hips']
```

Wildlife rigs match none of them — Zooba hips are `Hips_JNT` — so auto-assign gave up
with *"Could not guess template from Hip bone"* and filled in nothing.

This appends extra columns at runtime, built from the studio's own rig standards at
`P:/tech_art/.../hik_animation_transfer/.../supported_rig_std/`. Those files map the
same slot names Flow Studio uses, so they drop straight in. Result on a Zooba rig:
**0 → 46 of 52 bones** auto-assigned.

Because it patches at runtime and lives outside `wd-maya-tools`, reinstalling or
updating Flow Studio does not wipe it.

Falls back to a baked-in snapshot when `P:` is unreachable. Regenerate that snapshot
with `tools_gen_flowstudio_snapshot.py`.

#### Known gaps in the Zooba mapping

Six slots stay blank: `LeftHandRing1-3` and `RightHandRing1-3`. This is not an
oversight — `zooba_game_art.json` maps Flow Studio's **Middle** slot to the rig's
`L_Ring*_JNT` joints and its **Pinky** slot to the rig's `L_Middle*_JNT` joints, and
defines no Ring slot at all. Ring and middle look transposed. It may be deliberate for
a four-finger hand, or a mistake in the studio file. Worth confirming with tech art
before relying on finger retargeting.

Two slots are filled by inference rather than from studio data, flagged as `DERIVED` in
the module: `LeftToeBase` / `RightToeBase`, taken from Zooba's
`LeftFootExtraFinger1` → `L_Toe_JNT`. Set `USE_DERIVED = False` to turn that off.
