# WRCG PTX Converter

Convert **WRC Generations** textures (`.PTX`) to `.DDS` and back, and use them to replace or add car liveries.

- Byte-exact: converting a game PTX to DDS and back gives an identical file (tested on 222 car textures).
- Supports DXT1 (BC1), DXT5 (BC3), BC4, BC5 and BC7 textures.
- Command line tool + simple GUI. Pure Python, no extra packages.

> Unofficial fan tool, not affiliated with KT Racing or Nacon. Back up your files before modding.

## Requirements

- Windows, **Python 3.8+** (Tkinter is included with the standard installer).
- Modding enabled in WRC Generations: run `WRCGUnpackager.exe` from [WRCGModTools](https://github.com/Avery3R/WRCGModTools) by Avery3R, then set `Engine.UsePkg = false;` in `Common\Settings\SETTINGS.CFG`. The game then reads the loose files in `Common\` and `WIN32\`.

## Using the converter

**GUI:** double-click `ptx_converter.bat`.

- *PTX → DDS (export):* pick a game texture and where to save the DDS.
- *DDS → PTX (import):* pick your edited DDS, the **original PTX** (used as template) and where to save the new PTX.
- *Colour + mask (liveries):* split a `BODY_DIFF` into colour and mask, and combine them back into a PTX (see below).

**Command line:**

```
python ptx_dds.py todds  BODY_DIFF.PTX  my_livery.dds
python ptx_dds.py toptx  my_livery.dds  BODY_DIFF.PTX  NEW_BODY_DIFF.PTX
python ptx_dds.py verify FILE.PTX [...]     # PTX -> DDS -> PTX round-trip check
python ptx_dds.py split   BODY_DIFF.PTX  colour.dds  mask.dds
python ptx_dds.py combine colour.dds  mask.dds  BODY_DIFF.PTX  NEW_BODY_DIFF.PTX   # "-" instead of mask.dds keeps the original mask
```

When importing, the DDS must have the **same format and size** as the original and include mipmaps. Extra small mipmaps are dropped automatically (the game stops at 4×4).

**Editing:** Paint.NET and GIMP open and save DDS natively; Photoshop needs the NVIDIA Texture Tools or Intel Texture Works plugin. Save liveries as **BC3/DXT5, 4096×4096, with mipmaps**.

### Colour and mask

The alpha channel of `BODY_DIFF` is not transparency: it is a mask (alpha 0 on the painted bodywork, 255 on the other parts). Image editors show it as transparency, so the livery looks empty. To paint without it:

1. **Split** the PTX: you get an opaque **colour** DDS (BC1/DXT1) and a **mask** DDS (BC4/ATI1, greyscale).
2. Paint the colour file and save it as **BC3/DXT5** (exact: its alpha is ignored) or BC1/DXT1, 4096×4096, **with mipmaps**. Leave the mask alone unless you need to change it (save it as BC4/ATI1 with mipmaps).
3. **Combine** colour + mask with the original `BODY_DIFF.PTX` as template. Without a mask the original one is kept.

Split and combine copy the compressed blocks, so an unedited colour + mask gives back the original PTX byte for byte. The only exception is a BC1 block saved in its 3-colour mode, which BC3 does not have: it is re-fitted to 4 colours and may change slightly, which is why BC3 is the safer choice for the colour.

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

## Replacing an existing livery

1. Back up the livery folder.
2. Export its `BODY_DIFF.PTX` to DDS, paint it, save as BC3/DXT5 4096×4096 with mipmaps.
3. Import it with the original `BODY_DIFF.PTX` as template.
4. Copy the new PTX over the original `BODY_DIFF.PTX` and start the game.

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
