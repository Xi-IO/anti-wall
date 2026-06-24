`assets/icons/equipment` keeps two layouts in parallel:

- Flat files at the top level are the legacy paths currently used by the viewer.
- Category folders below are the curated set of demo-relevant equipment icons copied from `assets/icons/png/`.

Category layout:

- `pistols/`
- `rifles/`
- `smgs/`
- `heavy/`
- `grenades/`
- `bomb/`
- `melee/`
- `gear/`

Notes:

- Knife finishes are stored by source file name, for example `knife_outdoor.png` for Nomad Knife and `knife_widowmaker.png` for Talon Knife.
- `grenades/` includes both `molotov.png` and `firebomb.png` because the demo / viewer paths use both Terrorist and CT naming.
- `gear/` contains non-gun equipment that may need HUD support later, such as `defuser`, `kevlar`, `helmet`, `assaultsuit`, and `taser`.
