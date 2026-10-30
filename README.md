# Lumen

A small image viewer with a real editor core: menus, selections, copy/cut/paste,
cropping, undo, folder navigation, slideshows and animated GIF/WebP playback.
Built with Python and Qt 6 (PySide6).

![Lumen icon](lumen/resources/lumen.svg)

## Features

- **View** PNG, JPEG, WebP, GIF, BMP, TIFF, ICO, TGA, PNM, XBM/XPM and SVG
- **Navigate** a folder with the arrow keys, the mouse wheel, or click-to-advance
- **Zoom** with Ctrl+wheel or pinch, fit to window, actual size, full screen
- **Select** with a rectangle, ellipse or freehand lasso (animated marching ants)
- **Edit** with copy, cut, paste and delete; pasted content floats and can be dragged
  into place before it is committed
- **Crop** to the selection, with undo
- **Undo/redo** backed by a configurable memory budget
- **Save / Save As** with a `.bak` copy kept before the first overwrite
- **Animate** GIF and WebP files, with pause/play and looping
- **Light and dark** themes, following the system when the platform reports one
- **Single window**, single instance, drag and drop, and a CLI

## Requirements

- Python 3.10 or newer
- Linux, macOS or Windows with a Qt 6 compatible desktop
- `PySide6` and `Pillow` (installed by the setup script)

## Setup

```bash
./setup.sh
./bin/lumen
```

`setup.sh` creates the virtualenv, installs the dependencies, and links the
launcher into `~/.local/bin/lumen`, so once `~/.local/bin` is on your `PATH` you
can just run `lumen`. The link points at this checkout, so edits take effect
immediately.

To do the link by hand:

```bash
mkdir -p ~/.local/bin
ln -sfn /path/to/lumen/bin/lumen ~/.local/bin/lumen
```

Or manually:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
./bin/lumen [file|folder]
```

To install a desktop entry:

```bash
mkdir -p ~/.local/share/applications
sed "s|@ROOT@|$PWD|g" lumen.desktop > ~/.local/share/applications/lumen.desktop
update-desktop-database ~/.local/share/applications
```

## Using Lumen

Open a file with **File › Open** (`Ctrl+O`), drag it onto the window, or pass it
on the command line. Opening a folder starts at the first image and lets you
step through the rest with `←`/`→`.

Selections are made with **Select › Selection** (`S` square, `C` circle,
`F` freehand). Copy, cut and paste work on the selection, or on the whole image
when nothing is selected. A pasted layer stays floating — drag it, nudge it with
the arrow keys, then press `Enter` to commit or `Esc` to throw it away.

**Save** (`Ctrl+S`) overwrites the original in its own format and keeps
`name.ext.bak` the first time. **Save As** (`Ctrl+Shift+S`) writes a new file.
Unsaved edits are flagged with a dot in the title and prompt before you navigate
away or close.

The full keyboard list and a settings reference are in **Help › Help** (`F1`).

## Settings

Settings are stored as JSON at `~/.config/lumen/settings.json` (or
`$XDG_CONFIG_HOME/lumen/settings.json`). The Settings window covers:

- **Appearance** — theme, transparency backdrop, smooth/nearest scaling, status bar
- **Navigation** — click-to-advance, arrow keys, wrap, subfolders, hidden files,
  sort order, wheel behaviour, preloading, slideshow and animation options
- **Editing and Saving** — `.bak` backups, unsaved prompts, EXIF handling when
  loading and saving, quality, save format, cut fill, paste position, undo budget
- **Startup** — window geometry, last folder, single instance

## Development

```bash
.venv/bin/pytest              # run headless with QT_QPA_PLATFORM=offscreen
.venv/bin/ruff check lumen tests
.venv/bin/ruff format lumen tests
```

Layout:

```
lumen/
  __main__.py        entry point, single instance, CLI
  main_window.py     menus, actions, saving, navigation, theme
  canvas.py          zoom/pan, marching ants, selection tools
  document.py        pixels, selection, floating layer, undo
  formats.py         loading, atomic saving, metadata, backups
  navigation.py      folder listing, ordering, prefetch
  settings.py        JSON settings schema
  settings_dialog.py settings window
  dialogs.py         About, licence, help
  resources/         icon, help document, licence
```

## Limits

- One image per window; opening another replaces the current image.
- Animated files are read-only in place — Save As writes the current frame.
- SVG opens as a static raster image and cannot be saved over.
- Camera raw formats, HEIF/HEIC and PDF are not decoded.
- Colour management is limited to preserving the embedded ICC profile.

## Licence

MIT © 2026 Ro Black <signaldirective@gmail.com>
