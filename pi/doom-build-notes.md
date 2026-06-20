# Running Doom on the LA070WV1-TD01 panel (raw framebuffer, no GPU/X/KMS)

The panel is driven by the Pi's DPI as a raw `/dev/fb0` (legacy fbdev, vc4-kms OFF,
no X server). So any Doom port must either write the framebuffer directly or use an
SDL build with a framebuffer video driver. Two ports are set up on the Pi.

## Option A — fbDOOM (simple, low-res 320x200)

Direct `/dev/fb0` writes, never changes the video mode → rock solid, never blanks.
Vanilla engine, so it only renders **320x200** (2x integer scale = 640x400, centered
with a border; a non-integer stretch to fill looks blocky).

- Source: `~/doom/fbDOOM-master/fbdoom`, built `make` (needs `libsdl1.2-dev` for sound).
- WAD: `~/doom/doom1.wad` (shareware).
- Local patches in `i_video_fbdev.c`: honor `finfo.line_length` (real stride 3136, not
  xres*bpp) and zero the borders — the panel's fb is 776x480 but padded to 784/row.
- WASD defaults set in `m_controls.c` (`key_up='w'` etc.); mouse read directly from
  `/dev/input/mouse0` in `i_input_tty.c` (SDL mouse is dead in the fbdev build),
  aim-only (data3=0). Config dir hack `homedir="/mnt"` → `getenv("HOME")` in `m_config.c`.

## Option B — prboom-plus (sharp, full-screen native 776x480)  ← preferred

Software renderer at any resolution, so it fills the panel sharply. The hard part is
the **SDL backend**: modern Debian ships **sdl12-compat** (the SDL 1.2 API on top of
SDL2), and SDL2 has NO raw-framebuffer driver here (kmsdrm needs KMS we don't have;
no X). Symptom: `Could not initialize SDL [fbcon not available]`, and `sdl-config
--version` reports `1.2.68` (real SDL 1.2 tops out at 1.2.15). So we build **genuine
SDL 1.2.15** (which has the `fbcon` driver) from source, static, into `~/sdl12`, and
build SDL_mixer/SDL_net against it too (else they'd drag in sdl12-compat → two SDLs).

### Build (all static into ~/sdl12; aarch64, gcc14, current glibc)

Common gotchas, applied to every old-source `./configure`:
- config.guess too old for aarch64 → `--build=aarch64-unknown-linux-gnu --host=...`
  (or copy `/usr/share/automake-*/config.{guess,sub}` in).
- gcc14 hard-errors on old C → `CFLAGS="-O2 -fcommon -Wno-incompatible-pointer-types
  -Wno-implicit-function-declaration -Wno-implicit-int -Wno-int-conversion -Wno-error"`.

1. **SDL 1.2.15** (`libsdl.org/release/SDL-1.2.15.tar.gz`):
   `./configure --prefix=$HOME/sdl12 --disable-video-x11 --enable-video-fbcon
   --disable-shared --enable-static ...` ; `make && make install`.
2. **SDL_mixer 1.2.12** and **SDL_net 1.2.8** (`libsdl.org/projects/...`):
   `PATH=$HOME/sdl12/bin:$PATH ./configure --prefix=$HOME/sdl12
   --with-sdl-prefix=$HOME/sdl12 --disable-shared --enable-static
   --disable-music-mp3/mod/ogg/flac ...`
3. **prboom-plus 2.5.0.7** (`sourceforge.net/projects/prboom-plus/.../2.5.0.7`):
   `PATH=$HOME/sdl12/bin:$PATH ./configure --disable-gl --with-sdl-prefix=$HOME/sdl12
   CPPFLAGS="-I$HOME/sdl12/include/SDL" LDFLAGS="-L$HOME/sdl12/lib" <CFLAGS above>`.
   Source patch: glibc removed `sys_siglist` → `sed s/sys_siglist[X]/strsignal(X)/`
   in both `i_system.c`.

### Two prboom code fixes that mattered (both crashed at startup)

- **`src/SDL/i_video.c` `I_FillScreenResolutionsList`**: `SDL_ListModes()` returns
  `(SDL_Rect**)-1` ("any resolution") with fbcon/dummy; the code did `if (modes)` then
  dereferenced `modes[i]` → segfault. Fixed: `if (modes && modes != (SDL_Rect **)-1)`.
- **Hardware surface on a padded-stride fb**: prboom defaults to `use_doublebuffer 1`
  → `SDL_DOUBLEBUF` → real-fb HW surface; SDL's internal `SDL_FillRect` in
  `SDL_SetVideoMode` then segfaults because our fb line is padded (3136 vs 776*4).
  Fix in config: `use_doublebuffer 0` → `SDL_SWSURFACE` (software shadow, blitted with
  correct stride — same path the standalone fbcon test used successfully).

### Static link order

SDL_mixer/SDL_net reference SDL symbols, so they must precede `-lSDL`. The build lists
`-lSDL` first → undefined `SDL_MixAudio`. Relink wrapping them in a group:
`make LIBS="-L$HOME/sdl12/lib -Wl,--start-group -lSDL_mixer -lSDL_net -lSDL
-Wl,--end-group -lpng -lz -lm -lpthread -ldl"`.

### Config (`~/.prboom-plus/prboom-plus.cfg`)

`videomode "32bit"` (match the 32bpp fb), `use_fullscreen 0` (fullscreen forces a
mode-change the fixed DPI can't follow → blank), `use_doublebuffer 0`,
`screen_resolution "776x480"` (= the framebuffer). Both `doom1.wad` and the built
`prboom-plus.wad` must live in `~/.prboom-plus/`.

Controls (modern WASD + mouse-turn-only): `key_up 0x77`(w) `key_down 0x73`(s)
`key_strafeleft 0x61`(a) `key_straferight 0x64`(d); `use_mouse 1`,
`mouse_sensitivity_vert 0` (no mouse-Y walking), `mouseb_fire 0` (left = fire).
prboom rewrites this cfg on clean exit, so edit it while prboom is not running.

### Running

fbcon needs a **real console terminal** — it fails over SSH (`Unable to open a console
terminal`). Run it at the Pi's physical console (keyboard attached), as user `pi`:
`SDL_VIDEODRIVER=fbcon SDL_FBDEV=/dev/fb0 ~/prboom/prboom-plus-2.5.0.7/src/prboom-plus
-iwad ~/.prboom-plus/doom1.wad`. Quit with **F10 → y**. SDL leaves the fbcon console
**blank on exit** (it doesn't repaint) — press Enter (any output) and the terminal is
back; a launcher ending in `clear` hides this. Driving it over SSH via `sudo openvt -s
-w -- ...` works but switches VTs and leaves the panel blank if the program exits
uncleanly (recover with `sudo chvt 1`, or reboot).

Debugging the startup segfaults: the dummy driver (`SDL_VIDEODRIVER=dummy`) runs over
SSH and reproduced the first crash for `gdb -batch -ex run -ex bt`; the fbcon-only
second crash needed gdb at the console with output redirected to a file.
