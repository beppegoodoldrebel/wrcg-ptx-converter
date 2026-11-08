# WRCG PTX Converter

Convert **WRC Generations** textures (`.PTX`) to `.DDS` and back, and use them to replace or add car liveries.

- Byte-exact: converting a game PTX to DDS and back gives an identical file (tested on 222 car textures).
- Supports DXT1 (BC1), DXT5 (BC3), BC4, BC5 and BC7 textures; normal maps are exported in a format image editors open and imported from BC5, BC3 or BC1 (see [Normal maps](#normal-maps)).
- Command line tool + simple GUI. Pure Python, no extra packages.

> Unofficial fan tool, not affiliated with KT Racing or Nacon. Back up your files before modding.

## Requirements

- Windows, **Python 3.8+** (Tkinter is included with the standard installer).
- Modding enabled in WRC Generations: run `WRCGUnpackager.exe` from [WRCGModTools](https://github.com/Avery3R/WRCGModTools) by Avery3R, then set `Engine.UsePkg = false;` in `Common\Settings\SETTINGS.CFG`. The game then reads the loose files in `Common\` and `WIN32\`.

## Using the converter

**GUI:** double-click `ptx_converter.bat`.

- *Livery workspace* (first tab): open a livery folder, or any PTX in it, and you get all its textures in one list, with format, size, a small preview and a status. `BODY_DIFF` appears twice, as *colour* and *mask* (see below). Select the textures you want (Ctrl/Shift for several) and **Export selected to DDS**: they go into a work folder, by default `Desktop\WRCG_TEXTURES\<car>\<livery>` (change it with *Change...*, open it with *Show in Explorer*). Paint the DDS files there, then **Save modified to PTX**: only the DDS files changed since they were exported are converted, and written back as the PTX files of the livery folder. Status: *not exported*, *exported* (unchanged), *modified*, *saved*. The first save of each texture keeps the original PTX in `<work folder>\ORIGINALI`, which is the template of later saves; **Restore originals** puts those back. A DDS with the wrong format or size (e.g. only a layer exported by the editor) is reported and its PTX is not written. The work folder remembers what was exported in `workspace.json`.
  - **Load DDS...** brings in a DDS made elsewhere (e.g. a colour painted from another livery's export) without copying it by hand: with one row selected and one file chosen, the file goes to that texture; otherwise each file goes to the texture its name ends with (`MUNARI_BODY_DIFF_COLOUR.DDS` → `BODY_DIFF` colour, `..._MASK.DDS` → mask). Loading a colour offers to load the `_MASK` file next to it too. Format, size and mipmaps are checked, then the texture shows as *modified*: **Save modified to PTX** writes it into the livery.
  - **Stickers (numbers, names)...** opens the sticker editor of the livery: race numbers, driver and co-driver names, flags, rally plates... (see [Stickers](#stickers-race-numbers-names-flags)).
- *Teams & drivers* (second tab): the teams editor (see [Teams and drivers](#teams-and-drivers)).
- *PTX → DDS (export):* pick a game texture and where to save the DDS.
- *DDS → PTX (import):* pick your edited DDS, the **original PTX** (used as template) and where to save the new PTX.
- *Colour + mask (liveries):* split a `BODY_DIFF` into colour and mask, and combine them back into a PTX (see below).
- Import and combine can **overwrite** an existing PTX, also the original used as template (you are asked first). The first time a PTX is overwritten, the old file is kept in `ORIGINALI\` next to it; later overwrites leave that copy alone, so it stays the real original.

**Command line:**

```
python ptx_dds.py todds  BODY_DIFF.PTX  my_livery.dds
python ptx_dds.py toptx  my_livery.dds  BODY_DIFF.PTX  NEW_BODY_DIFF.PTX
python ptx_dds.py verify FILE.PTX [...]     # PTX -> DDS -> PTX round-trip check
python ptx_dds.py split   BODY_DIFF.PTX  colour.dds  mask.dds
python ptx_dds.py combine colour.dds  mask.dds  BODY_DIFF.PTX  NEW_BODY_DIFF.PTX   # "-" instead of mask.dds keeps the original mask
```

`NEW_BODY_DIFF.PTX` can also be `BODY_DIFF.PTX` itself: the original is kept in `ORIGINALI\` the first time.

When importing, the DDS must have the **same format and size** as the original and include mipmaps. Extra small mipmaps are dropped automatically (the game stops at 4×4). Normal maps are the exception, see below.

### Normal maps

The game's normal maps (`*_NRM`) are **BC5 signed** (the normal's x and y, flat = 0), which most image editors cannot open or save. So:

- **Export** writes them as **BC5 unsigned** with a legacy `ATI2` header (flat = 128: a red/green image, mid-grey where the surface is flat), which GIMP, Paint.NET and the Photoshop plugins open.
- **Import** (and *Load DDS...* / *Save modified to PTX* in the livery workspace) accepts, for a normal map, any of: **BC5** unsigned (`ATI2`, or DX10 `BC5_UNORM`) or signed, **BC3/DXT5** with x, y in red, green (or `DXT5nm`: x in alpha, red unused, recognised automatically), **BC1/DXT1** with x, y in red, green. Same size as the original and with mipmaps, as for the other textures. Blue is ignored (the game rebuilds z).

The conversion copies the compressed blocks (endpoints shifted between unsigned and signed, colour-block channels moved into BC5 blocks), nothing is re-compressed. Export and import of an unedited normal map give back the original PTX byte for byte (tested on 685 car normal maps). Save edited normal maps as **BC5/ATI2** for the best quality: BC3/BC1 store red with 5 bits only.

A normal map made elsewhere must use the same green-channel direction as the game's: if its relief looks inverted in game (bumps that look like dents), invert its green channel and import it again.

**Editing:** Paint.NET and GIMP open and save DDS natively; Photoshop needs the NVIDIA Texture Tools or Intel Texture Works plugin. Save liveries as **BC3/DXT5, 4096×4096, with mipmaps**.

### Colour and mask

The alpha channel of `BODY_DIFF` is not transparency: it is a mask (alpha 0 on the painted bodywork, 255 on the other parts). Image editors show it as transparency, so the livery looks empty. To paint without it:

1. **Split** the PTX: you get an opaque **colour** DDS (BC1/DXT1) and a **mask** DDS (BC4/ATI1, greyscale).
2. Paint the colour file and save it as **BC3/DXT5** (exact: its alpha is ignored) or BC1/DXT1, 4096×4096, **with mipmaps**. Leave the mask alone unless you need to change it (save it as BC4/ATI1 with mipmaps).
3. **Combine** colour + mask with the original `BODY_DIFF.PTX` as template. Without a mask the original one is kept.

Split and combine copy the compressed blocks, so an unedited colour + mask gives back the original PTX byte for byte. The only exception is a BC1 block saved in its 3-colour mode, which BC3 does not have: it is re-fitted to 4 colours and may change slightly, which is why BC3 is the safer choice for the colour.

## Stickers (race numbers, names, flags)

Race numbers, driver and co-driver names, flags, rally plates and the career sponsors are not painted in the texture: the game draws them on top of `BODY_DIFF`, where `Common\Tuning\LIVERIES.LUA` says. Each entry of that file (named after a `CARS.CFG` livery entry, in upper case) has a list of stickers:

```lua
LM_FIAT_131_ABARTH_ALEN = {
	EditorDiffuseTexture = "DATA:/GRAPH/CARS/LEGEND_MOD/WRC_70S/FIAT_131_ABARTH/ALEN/BODY_DIFF.PTX",
	Stickers = {
		{
			Type = LiveryType.NumberBlack,     -- what is drawn (27 types, see the LiveryType table at the top)
			Position = {0.394020, 0.880613},   -- texture coordinates (0-1, top-down) of a corner of the box
			Size = {0.078000, 0.068000},       -- width and height
			Rotation = -0.273000,              -- degrees, clockwise, around Position
			Order = 1,
		},
```

The text and numbers themselves come from the team (`TEAMS.CFG`: driver names, nationality for the flags, `StickerNumber`); `LIVERIES.LUA` only says where and how they are drawn. Some types seen in the game: `DriverName`/`CodriverName` (white, stretched to fill the box), `DriverNameBlack`/`CodriverNameBlack` (black, natural width, starting from the box's left side, no flag), `DriverNameFlag`/`DriverFlagName` (name with flag), `DriverFlag`, `NumberBig`/`NumberBlack`/`NumberWhite`/`NumberSmall`, `CountrySticker`(`_left`, `_right`, `_top`, `_back`) for the rally plates, `WindScreenCountry`, `CategorySticker`, `Career*Sponsor`.

**Sticker editor** (*Livery workspace* → *Stickers (numbers, names)...*). It finds the `LIVERIES.LUA` entries that use the opened livery's `BODY_DIFF` (by `EditorDiffuseTexture`, and through `CARS.CFG` + PACLOG), shows the texture with a box for each sticker (colour by kind: names cyan, black names magenta, flags green, numbers yellow, plates orange, career sponsors red; the thick side is the top of the text) and lets you:

- click a box to select it, drag it to move it, drag the square handle to resize it, drag the round handle to rotate it (Shift: 15° steps);
- type exact values (type, X, Y, width, height, rotation, order) in the side panel, Enter applies;
- arrow keys: move by one texel of the 4096 texture (Shift: 10); Delete, Ctrl+D duplicate, Ctrl+Z / Ctrl+Y undo / redo, Ctrl+S save;
- **Add**, **Duplicate**, **Delete**, **Copy from entry...** (take all the stickers of another livery, e.g. a legend one), **Reload from file**, **Original stickers** (those of the file as it was before the first save);
- zoom 50-400% (Ctrl+wheel), dim the parts that are not painted bodywork (from the mask; off when the window opens), drag the view with the middle button.

**Save to LIVERIES.LUA** writes only the stickers of the edited entries (all the entries of the livery at once, e.g. a livery and its `MOD_` copy, when they have the same stickers) and checks the file before writing. The first save keeps the original file in `Common\Tuning\ORIGINALI\LIVERIES.LUA`. The game reads the file when it starts, so restart it to see the changes. Mod installers that write their own `LIVERIES.LUA` replace these changes.

## Teams and drivers

The teams of every championship (WRC, WRC2, Junior, Legends...) are in `Common\Tuning\FACTORIES\TEAMS.CFG`:

| Field | Meaning |
|---|---|
| `TeamID` | `WrcTeamDriversId.eTeam...`: **fixed**, the list is inside the game executable, so no new IDs can be made |
| `TeamName` | `LocalesId.TEAM_...`: one of the team names of the game texts (`Common\SCRIPTS\LOCALISATION.LUA`, text in `Common\LOCALISATION\*.PLOC`) |
| `TeamConstructor` | make shown in the menus |
| `PilotInfo` | driver: `Country = WrcNationality.XX`, `FirstName`, `LastName`, `PathLastName` (3D model and helmet: a legend driver's folder, or `CUSTOM` for a generic one), `Skin` (suit) |
| `CopilotInfo` | co-driver: nationality, first and last name |
| `Car` | the `CARS.CFG` livery entry the team drives |
| `StickerNumber` | race number |
| `PilotLevel` | AI level: `Global`, `Limit` (`PilotLimit.Best/Average/Bad`), snow/tarmac/gravel, high/mid/low speed, reliability |
| `Rallies` | the rallies the team enters (`Rally_01`...) |
| `TeamColor` | colour in the menus (6 hex digits) |
| `TeamOrderIndex`, `PilotIndexInTeam` | order of the teams, first/second... driver of a team |

A disabled team is the same block with every line commented out (`--`).

**Teams editor** (*Teams & drivers* tab → *Open teams editor*; the game folder is found automatically or chosen with *Browse...*):

- The list shows every team by championship (from its car's category), with crew, number, car and state. Disabled teams are shown in grey: they are the **free places** for new crews, since team IDs cannot be created.
- The form edits all the fields above: team name (with its English text), make, car, number, colour (click the swatch for a colour picker), order, driver and co-driver (nationality, names, model, suit), AI level and rallies. **Apply** (or Enter) keeps the changes in memory; only the changed lines of the file are rewritten.
- **New crew...** adds a crew without looking for a free team by hand: choose a free ID (the dialog shows how many are left), category, car, driver, co-driver and number. Team name, make, AI level, rallies and colour come from a team with the same car or category; change them in the form afterwards. IDs of disabled teams come first. A few IDs the game knows but never uses are listed as "never tried in game": test one before relying on them. The total stays limited, because the IDs are fixed in the game executable.
- **Enable / disable** a team (with a warning if `CONTESTS.CFG` uses its ID for a challenge). **Copy crew from team...** copies driver, co-driver and AI level from another team, e.g. a legend card.
- **Shared livery:** choose another *Car*; several teams can drive the same livery entry.
- **Dedicated livery...** gives the team its own copy of the livery it drives: a new livery folder next to the original (materials rewritten to it), a new PACLOG, a new `CARS.CFG` entry (same category, model and tyres), the same tyre sets in `TYRES.CFG` and the same stickers in `LIVERIES.LUA`; the team then drives it. Paint it afterwards from the livery workspace.
- **Stickers...** opens the sticker editor of the team's livery.
- **Check** lists the problems: missing car or livery package, two active teams with the same ID (error, blocks saving), a car without tyres or without stickers, the same number twice in a championship, a disabled team used by a challenge.
- **Save all** writes `TEAMS.CFG`, `CARS.CFG`, `TYRES.CFG` and `LIVERIES.LUA`; the first save of each keeps the original in an `ORIGINALI` folder next to it. Restart the game to see the changes. Mod installers that write these files replace the changes.

Things to keep in mind: the Season menu groups teams by car model (`Shape` of the car), and the Junior season only shows `FordFiesta_R2` cars; a team name can only be one of the game's `TEAM_...` texts.

## How liveries are stored

Each livery is a folder, e.g. `WIN32\GRAPH\CARS\LEGENDS\SUBARU_IMPREZA_S5\MCRAE\`:

| File | Content |
|---|---|
| `BODY_DIFF.PTX` | the livery artwork (DXT5 4096×4096, mask in the alpha channel) – **this is what you paint** |
| `BODY_IOR.PTX` | reflections / roughness (DXT1) |
| `*.PMA` | materials; they contain the absolute paths of the textures above |

The car model, normal maps, damage and dirt textures are shared by all liveries of a car. Most legend cars also have a `NEUTRE` (plain white) livery, a good canvas to start from (the Impreza has none).

Two more pieces link a livery to the game:

- **PACLOG** – `WIN32\PACLOG\CUSTOMPAC\CARS\LEGEND\<Car>\<Livery>.PACLOG`: a plain text list of every file to load (`0x7FFFFFFF DATA:/path` per line). Files not listed here are never loaded.
- **CARS.CFG** – `Common\Tuning\FACTORIES\CARS.CFG`: each livery entry points to its PACLOG with `LiveryPaclog`.
- **LIVERIES.LUA** – `Common\Tuning\LIVERIES.LUA`: where the race numbers, names and flags are drawn on the livery (see [Stickers](#stickers-race-numbers-names-flags)).

## Replacing an existing livery

1. Back up the livery folder.
2. Export its `BODY_DIFF.PTX` to DDS, paint it, save as BC3/DXT5 4096×4096 with mipmaps.
3. Import it with the original `BODY_DIFF.PTX` as template, saving it over that same file (the original is kept in `ORIGINALI\`), or use the livery workspace.
4. Start the game.

## Adding a new livery

1. **Create the folder.** Copy a livery folder (e.g. `NEUTRE`) to a new one whose name has the **same length** (e.g. `NEUTRE` → `MOD_01`). The `.PMA` files store each path with its length in front, so a same-length name lets you edit them with a plain byte replace.
2. **Fix the materials.** In every `.PMA` of the new folder replace `/NEUTRE/` with `/MOD_01/` (binary-safe, same length).
3. **Add your texture.** Import your DDS with the original `BODY_DIFF.PTX` as template and save it as `MOD_01\BODY_DIFF.PTX`. Keep the copied `BODY_IOR.PTX`.
4. **Create the PACLOG.** Copy an existing livery PACLOG and replace the livery folder paths with `MOD_01`. A legend livery PACLOG (e.g. `Makinen.PACLOG`) gives period driver models; `Neutre.PACLOG` gives generic modern helmets. Then **make sure every file referenced by your `.PMA` files is listed**: e.g. the `NEUTRE` glass material uses `DATA:/TEXTURES/COMMON_MAP/BLACK_ALPHA.PTX`, and if it is missing the windows turn opaque yellow-green.
5. **Register the livery in `CARS.CFG`.** Copy a livery entry of the same car with a new name and point `LiveryPaclog` to the new PACLOG:
   ```lua
   Mitsubishi_Lancer_Evo_V_1998_Mod01 =
   {
       BaseCar      = Mitsubishi_Lancer_Evo_V_1998,
       Skin         = "Mitsubishi_Lancer_Evo_V_1998",
       LiveryPaclog = "DATA:/PACLOG/CUSTOMPAC/Cars/LEGEND/Mitsubishi_Lancer_Evo_V_1998/MOD_01.PACLOG",
   },
   ```
6. **Give it tyres in `TYRES.CFG`.** Tyre sets are assigned by livery name (`Car = "..."` or `Cars = { ... }`). Add the new name next to the original livery in each of its tyre sets, otherwise the car has no tyres.
7. **Use it.** Set it as the `Car` of a team in `TEAMS.CFG`, or select it in game.

## Known limitations

- The livery thumbnail in menus is taken from the `Skin` image of the livery you copied.
- Uncompressed RGBA textures (a few dirt masks) are not supported; livery textures are not affected.
- Some PTX header fields are undocumented; they are copied from the original PTX, which is why import needs it as a template.

## Credits

- [Avery3R](https://github.com/Avery3R) – [WRCGModTools](https://github.com/Avery3R/WRCGModTools) (unpacker / enabling mods).

## License

[MIT](LICENSE). WRC Generations and its assets belong to their respective owners; this repository contains no game files.
