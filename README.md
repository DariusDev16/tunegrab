# TuneGrab

```
 ██████  ██   ██ ███    ██ █████   ██████  █████   ██████
 ██   ██ ██   ██ ████   ██ ██   ██ ██      ██   ██ ██    ██
 ██████  ██   ██ ██ ██  ██ ██████  ██      ██████  ██    ██
 ██      ██   ██ ██  ██ ██ ██      ██      ██   ██ ██    ██
 ██       █████  ██   ████ ██      ██████  ██   ██  ██████
```

**Download a whole Spotify playlist** — reads the playlist, searches every
track on YouTube, picks the best match, and saves everything into one folder.

![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)
![Python: 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)
![Deps: 1](https://img.shields.io/badge/dependencies-1-brightgreen.svg)

---

## What it does

1. **Reads** the Spotify playlist from its `/embed/` page — no account, no API key.
2. **Builds** an `artist - title` query per track, splitting multi-artist names correctly.
3. **Scores** the YouTube results on title similarity, artist presence and duration proximity.
4. **Downloads** the winner with **yt-dlp** and converts via **ffmpeg**.
5. **Saves** to `./<Playlist Name>/`, indexed and sorted, plus `tracklist.txt` and `playlist.m3u`.

## Why matching is scored, not "take the first hit"

Grabbing the top search result fails constantly:

- The same title exists as a **live**, **remix**, **acoustic** or **cover** version.
- Results are full of boilerplate — `(Lyrics)`, `(Letra)`, `(Official Video)`, AI slop.
- **Durations rarely match.** A track that is 3:08 on Spotify is often 3:46 on YouTube because the official release carries an intro and outro. A strict duration filter would reject the *correct* match — the exact bug this scorer was written to avoid.

So TuneGrab strips boilerplate (`feat.`, `Remastered`, `(Lyrics)`, `4K`, …) before comparing, detects alternative-version markers, and scores:

```
score = 0.42·title_similarity
      + 0.18·token_overlap
      + 0.25·artist_match
      + 0.15·duration_proximity
      − version_penalty
```

Title and artist carry 67% of the weight; duration is only a light tiebreaker.
Alternative versions are penalised **unless the playlist asked for them**.
Anything below `--min-score` is reported as unmatched rather than silently
downloading the wrong song.

## Requirements

| | |
|---|---|
| Python | 3.9+ |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | the only runtime dependency |
| ffmpeg | optional — needed for conversion |

## Install

```bash
git clone https://github.com/YOUR_USER/tunegrab.git
cd tunegrab
pip install -r requirements.txt
```

### ffmpeg

| Platform | Command |
|---|---|
| Windows | `winget install Gyan.FFmpeg` |
| macOS | `brew install ffmpeg` |
| Debian/Ubuntu | `sudo apt install ffmpeg` |

TuneGrab auto-detects ffmpeg (including the one bundled with
[spotdl](https://github.com/spdl-rs/spotdl) at `~/.spotdl/ffmpeg`). Without it,
the tool still runs — it just saves YouTube's original format (`.webm`)
instead of converting. Pass `--ffmpeg /path/to/ffmpeg` to override.

## Usage

**Windows** — double-click `tunegrab.bat`. It asks for the playlist link, downloads,
and keeps the window open so you can read the result.

**Any OS** — run it directly:

```bash
python tunegrab.py <spotify-url>
```

```
tunegrab https://open.spotify.com/playlist/5kT0R0PpFjRsThlBwvjfgn
```

### Options

| Flag | Description |
|---|---|
| `-o, --out PATH` | destination base folder (default: current dir) |
| `-c, --concurrency N` | parallel YouTube searches (default 4) |
| `--download-slots N` | parallel downloads (default 2; higher risks 403) |
| `-f {mp3,m4a,opus,flac}` | output format (default `mp3`) |
| `-q, --quality N` | bitrate (default `192`) |
| `--list` | list the playlist, download nothing |
| `--dry-run` | show the match plan without downloading |
| `--min-score F` | minimum score to accept a match (default `0.55`) |
| `--force` | accept the best candidate regardless of score |
| `--attempts N` | how many ranked candidates to try if a download fails |
| `--backoff F` | base wait between download attempts, seconds |
| `--search-limit N` | candidates fetched per track (default 8) |
| `--query-suffix S` | extra search text, e.g. `audio` |
| `--ffmpeg PATH` | explicit ffmpeg binary |
| `--no-ffmpeg` | don't convert; keep original format |
| `--no-skip-existing` | re-download files that already exist |
| `--no-banner` / `--no-anim` | skip / skip animation |

Also works on **albums** and **single tracks**, not just playlists.

### Examples

```bash
# see what would be downloaded, download nothing
python tunegrab.py <url> --dry-run

# higher bitrate opus into ~/Music
python tunegrab.py <url> -f opus -q 160 -o ~/Music

# strict matching
python tunegrab.py <url> --min-score 0.75

# slow and steady on flaky networks (avoids 403)
python tunegrab.py <url> --download-slots 1 --backoff 3
```

## Output

```
favorites/
  01 - Plutonio - Acordar.mp3
  02 - Richie Campbell, Plutonio - C'est La Vie.mp3
  ...
  tracklist.txt
  playlist.m3u
```

Re-running is safe — anything already downloaded is skipped, so you can just
run the command again after a failure to fill the gaps. Tracks that failed land
in `nao-baixadas.txt` ("not downloaded").

## Troubleshooting

**The `.bat` window closes instantly.** Run it from a terminal to see the error:
`tunegrab.bat --help`. It needs a playlist link; with none it exits immediately.

**`python` opens the Microsoft Store.** That's the Windows App Execution Alias
shim, not a real interpreter. Use `py` instead, or reinstall Python with
"Add Python to PATH" ticked.

**403 errors.** YouTube rate-limits bursts. TuneGrab already retries with
backoff, switches player client, and falls back to the next ranked candidate.
If it persists, slow it down: `--download-slots 1 --backoff 3`. Keep yt-dlp
current with `pip install -U yt-dlp`.

**Wrong song downloaded.** Check the plan with `--dry-run`, then tighten with
`--min-score 0.75`, or add `--query-suffix "audio"`.

**Large playlists (>100 tracks).** The `/embed/` page caps out around 100
items. Pass Spotify API credentials for full pagination:

```bash
export SPOTIFY_CLIENT_ID=...
export SPOTIFY_CLIENT_SECRET=...
```

## Note on YouTube Music

yt-dlp's `ytmsearch` prefix is currently broken upstream
(`Unsupported url scheme: "ytmsearch"`), and `music.youtube.com/search` serves
a JavaScript stub that can't be scraped without cookies. TuneGrab searches
regular YouTube, which indexes the same audio.

## Legal

TuneGrab is a tool, not a content service. It ships with no music and downloads
nothing on its own. Downloading copyrighted material may be illegal depending
on your jurisdiction — use it for your own listening, personal backups, or
content you have the rights to, and don't redistribute what you download.
Respect YouTube's Terms of Service and the rights of the artists.

## Contributing

Issues and pull requests are welcome. Please keep it dependency-light — the only
runtime dependency is `yt-dlp`, by design.

### Running the tests

```bash
python -m unittest discover -s tests -v
```

The suite covers the matching scorer, title normalisation and filename
sanitisation — including regression tests for two real bugs found while building
this (a greedy `feat` pattern that deleted track titles, and duration mismatch
causing wrong matches). Downloads are deliberately *not* tested in CI: YouTube
blocks datacenter IPs, so a network test would be flaky by nature.

CI runs on Ubuntu and Windows, Python 3.9 and 3.12.

## License

MIT — see [LICENSE](LICENSE).