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
second crash needed gdb at the console with output redirected to a file. The dummy
driver is also the way to debug audio/music over SSH (audio doesn't need a console).

## Audio — Bluetooth speaker + MIDI music

### Bluetooth speaker (Beats Pill) via bluez-alsa

The Pi runs headless (no PipeWire/PulseAudio session), and SDL outputs to ALSA, so
**bluez-alsa** is the right bridge (a system service exposing the BT speaker as an ALSA
PCM — no desktop session needed). `apt install bluez-alsa-utils`; the Debian service
already runs `bluealsa -S -p a2dp-source -p a2dp-sink` (a2dp-source is what we need —
Pi sending to a speaker). Pair/connect with `bluetoothctl` (pair, trust, connect MAC).
Gotcha: a speaker bonded to a phone won't connect until unpaired there; a paired PCM
appears as `bluealsa:DEV=<MAC>,PROFILE=a2dp` / `bluealsa-cli list-pcms`. Route ALSA's
default to it with `~/.asoundrc` (`pcm.!default` → `type plug` → `type bluealsa
device "<MAC>" profile "a2dp"`; the `plug` resamples Doom's ~11 kHz to A2DP's 44.1 kHz).
Then run with `SDL_AUDIODRIVER=alsa`. Expect ~150–250 ms A2DP latency on SFX.

### MIDI music (the painful part — three separate fixes)

prboom plays Doom's MUS music by converting to MIDI and handing it to SDL_mixer, whose
built-in timidity renders it. All three of these had to be right:

1. **`music_card -1`, NOT 0.** In `s_sound.c`: `if (!mus_card ...) return;` — music plays
   only when `mus_card` is non-zero, so `-1` = autodetect = ENABLED and `0` = DISABLED.
   (Setting it to 0 silently stops `I_RegisterSong` from ever being called.)
2. **GUS patches for timidity.** `apt install timidity freepats`. The stock
   `/etc/timidity/timidity.cfg` points at a `.sf2` soundfont, which SDL_mixer's *old*
   timidity can't read — it needs GUS `.pat` files. Run with
   `TIMIDITY_CFG=/etc/timidity/freepats.cfg` (patches under /usr/share/midi/freepats).
   Verify the chain independently with a tiny `Mix_LoadMUS` test on a `.mid` file.
3. **Code fix: force the file path for converted MIDI.** In `src/SDL/i_sound.c`
   `I_RegisterSong`, prboom loads the converted MIDI via `Mix_LoadMUS_RW` (from memory),
   but SDL_mixer 1.2's RW-MIDI path is silent (timidity needs a real file). Patch:
   set `rw_midi = NULL` after `SDL_RWFromMem(outbuf, outbuf_len)` so it falls through to
   `M_WriteFile(music_tmp, ...)` + `Mix_LoadMUS(music_tmp)`. (Symptom before: the
   `/tmp/prboom-plus-music-*` temp file was 0 bytes and music was silent.)

Note: don't blank the `mus_*` music-pack substitutions to `""` (that disables a track);
leave them at their defaults (`*.mp3` names) — the files don't exist so prboom falls
back to the WAD MIDI lump. freepats sounds lo-fi but it's real instrument MIDI.

Final run line:
`TIMIDITY_CFG=/etc/timidity/freepats.cfg SDL_VIDEODRIVER=fbcon SDL_FBDEV=/dev/fb0
SDL_AUDIODRIVER=alsa ./prboom-plus -iwad ~/.prboom-plus/doom2.wad`
