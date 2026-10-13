#!/usr/bin/env python3
"""
TuneGrab — Baixa playlists inteiras do Spotify via YouTube + yt-dlp.

Fluxo:
  1. Le a playlist do Spotify (pagina /embed/ — sem credenciais).
  2. Monta "artista - titulo" e pesquisa no YouTube via yt-dlp.
  3. Pontua os candidatos (titulo + artista + duracao) e escolhe o melhor.
  4. Baixa o audio e converte com ffmpeg.
  5. Salva tudo numa pasta nomeada com a playlist.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures as futures
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "TUNEGRAB"
APP_VERSION = "1.0.0"
APP_TAGLINE = "spotify playlist  ->  youtube  ->  your folder"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------
def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


COLOR = _supports_color()


def _c(text: str, r: int, g: int, b: int) -> str:
    if not COLOR:
        return text
    return f"\x1b[38;2;{r};{g};{b}m{text}\x1b[0m"


def dim(text: str) -> str:
    return f"\x1b[2m{text}\x1b[0m" if COLOR else text


def bold(text: str) -> str:
    return f"\x1b[1m{text}\x1b[0m" if COLOR else text


# Cores nomeadas. Python < 3.12 (PEP 701) nao permite backslash dentro da parte
# de expressao de um f-string, entao escapes literais direto em {bold('...')}
# viram SyntaxError em 3.9/3.10/3.11. Use sempre tint(TEXTO, COR).
_RESET = "\x1b[0m"
BOLD_RED = "\x1b[1;31m"
BOLD_GREEN = "\x1b[1;32m"
BOLD_YELLOW = "\x1b[1;33m"
BOLD_CYAN = "\x1b[1;36m"
PLAIN_GREEN = "\x1b[32m"
PLAIN_YELLOW = "\x1b[33m"


def tint(text: str, code: str) -> str:
    return f"{code}{text}{_RESET}" if COLOR else text


# --- Banner ASCII ----------------------------------------------------------
# Fonte block 5 linhas / 7 colunas por letra.
_FONT = {
    "A": [" █████ ", "██   ██", "███████", "██   ██", "██   ██"],
    "B": ["██████ ", "██   ██", "██████ ", "██   ██", "██████ "],
    "C": [" ██████", "██     ", "██     ", "██     ", " ██████"],
    "D": ["██████ ", "██   ██", "██   ██", "██   ██", "██████ "],
    "E": ["███████", "██     ", "█████  ", "██     ", "███████"],
    "F": ["███████", "██     ", "█████  ", "██     ", "██     "],
    "G": [" ██████", "██     ", "██  ███", "██   ██", " █████ "],
    "H": ["██   ██", "██   ██", "███████", "██   ██", "██   ██"],
    "I": ["███████", "  ██  ", "  ██  ", "  ██  ", "███████"],
    "J": ["███████", "    ██", "    ██", "██  ██ ", " ████ "],
    "K": ["██   ██", "██  ██ ", "████   ", "██  ██ ", "██   ██"],
    "L": ["██     ", "██     ", "██     ", "██     ", "███████"],
    "M": ["███   ███", "████ ████", "██ ███ ██", "██  █  ██", "██     ██"],
    "N": ["██   ██", "███  ██", "████ ██", "██ ████", "██  ███"],
    "O": [" █████ ", "██   ██", "██   ██", "██   ██", " █████ "],
    "P": ["██████ ", "██   ██", "██████ ", "██     ", "██     "],
    "Q": [" █████ ", "██   ██", "██   ██", "██ █ ██", " ████ ██"],
    "R": ["██████ ", "██   ██", "██████ ", "██  ██ ", "██   ██"],
    "S": [" ██████", "██     ", " █████ ", "     ██", "██████ "],
    "T": ["███████", "  ██  ", "  ██  ", "  ██  ", "  ██  "],
    "U": ["██   ██", "██   ██", "██   ██", "██   ██", " █████ "],
    "V": ["██   ██", "██   ██", "██   ██", " ██ ██ ", "  ███  "],
    "W": ["██     ██", "██  █  ██", "██ ███ ██", "████████", "██     ██"],
    "X": ["██   ██", " ██ ██ ", "  ███  ", " ██ ██ ", "██   ██"],
    "Y": ["██   ██", " ██ ██ ", "  ███  ", "  ██  ", "  ██  "],
    "Z": ["███████", "    ██ ", "   ██  ", " ██    ", "███████"],
    " ": ["       "] * 5,
}

# Rosa -> laranja -> roxo (estilo synthwave)
_GRAD = [(255, 45, 120), (255, 140, 40), (150, 80, 255)]


def _gradient(t: float) -> tuple[int, int, int]:
    """Interpola na paleta synthwave. t vai de 0..1."""
    t = min(max(t, 0.0), 1.0)
    seg = len(_GRAD) - 1
    pos = t * seg
    i = int(pos)
    if i >= seg:
        return _GRAD[-1]
    f = pos - i
    a, b = _GRAD[i], _GRAD[i + 1]
    return (round(a[0] + (b[0] - a[0]) * f),
            round(a[1] + (b[1] - a[1]) * f),
            round(a[2] + (b[2] - a[2]) * f))


def ascii_lines(text: str, tracking: int = 2) -> list[str]:
    rows = [""] * 5
    for ch in text.upper():
        glyph = _FONT.get(ch, _FONT[" "])
        for i in range(5):
            rows[i] += glyph[i] + " " * tracking
    return [r.rstrip() for r in rows]


def print_banner(animate: bool = True) -> None:
    word = "TUNEGRAB"
    art = ascii_lines(word)
    width = max(len(l) for l in art)

    if animate and COLOR and sys.stdout.isatty():
        frames = 26
        for f in range(frames):
            off = f / (frames - 1)
            out = []
            for row in art:
                line = []
                for col, ch in enumerate(row):
                    t = (col / max(width - 1, 1)) - off
                    line.append(_c(ch, *_gradient(t)))
                out.append("".join(line))
            sys.stdout.write("\x1b[H\x1b[2J")
            sys.stdout.write("\n".join(out) + "\n")
            sys.stdout.flush()
            time.sleep(0.045)
        sys.stdout.write("\n")
    else:
        for row in art:
            out = []
            for col, ch in enumerate(row):
                out.append(_c(ch, *_gradient(col / max(width - 1, 1))))
            print("".join(out))

    bar = "─" * min(width, 72)
    print(_c(bar, *_gradient(0.5)))
    print("  " + bold(APP_TAGLINE) + dim(f"   v{APP_VERSION}"))
    print()


_print_lock = threading.Lock()


def log(msg: str = "") -> None:
    with _print_lock:
        print(msg, flush=True)


# --------------------------------------------------------------------------
# Utilidades de texto
# --------------------------------------------------------------------------
# Ruido de titulos do YouTube. Cuidado: o padrao de "feat" precisa ser
# ANCORADO no fim — um "feat" guloso ate o fim da string apagava o proprio
# titulo ("C'est La Vie (Official Video)" -> "richie campbell").
_BRACKET = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")
_TRAILING_FEAT = re.compile(r"\s+\b(?:feat|ft|featuring)\b\.?\s+.*$", re.IGNORECASE)
_TAIL_JUNK = re.compile(r"\blen\s*[,:]\s*\d+\s*$", re.IGNORECASE)
_NOISE_WORDS = re.compile(
    r"\b(?:remaster(?:ed)?|deluxe|bonus\s+track|explicit|clean\s+version"
    r"|lyrics?|lyric|letra|parlodia|instrumental|karaoke|cover"
    r"|official|audio|visuali[sz]er|m/?v|music\s+video"
    r"|hd|hq|4k|8k|1080p|720p|high\s+quality|with\s+lyrics|colour\s+coded"
    r"|size|stereo)\b",
    re.IGNORECASE,
)

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)

# Versoes alternativas. O limpador de ruido APAGA essas palavras, entao elas
# precisam ser detectadas antes — senao uma versao "live" passa por original.
_VERSION_RE = re.compile(
    r"\b(live|vivo|acoustic|ac[oú]stico|ac[oú]stica|unplugged|remix|bootleg"
    r"|karaoke|instrumental|cover|reprise)\b", re.IGNORECASE)


def version_tags(s: str) -> set[str]:
    """Marcadores de 'versao' presentes num titulo."""
    t = _PUNCT.sub(" ", strip_accents(s or "").lower())
    return {_VERSION_RE.sub(r"\1", m).strip() for m in _VERSION_RE.findall(t)}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def norm(s: str) -> str:
    """Normaliza para comparacao: sem acentos, minusculas, sem ruido de titulo."""
    s = strip_accents(s or "").lower()
    s = _BRACKET.sub(" ", s)
    s = _TAIL_JUNK.sub(" ", s)
    s = _TRAILING_FEAT.sub(" ", s)
    s = _NOISE_WORDS.sub(" ", s)
    s = _PUNCT.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_artists(subtitle: str) -> list[str]:
    """Spotify separa artistas por NBSP (\xa0) e virgula."""
    raw = (subtitle or "").replace("\xa0", " ")
    parts = re.split(r"\s*[,;]\s*|\s+&\s+|\s+e\s+", raw)
    out, seen = [], set()
    for p in parts:
        p = strip_accents(p).strip(" -·•")
        if p and p.lower() not in seen and not re.fullmatch(r"\d{4}", p):
            seen.add(p.lower())
            out.append(p)
    return out


def clean_title(title: str) -> str:
    t = _BRACKET.sub(" ", title or "")
    t = _TRAILING_FEAT.sub(" ", t)
    t = _NOISE_WORDS.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip(" -–—|·•")


_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


def sanitize(name: str, max_len: int = 110) -> str:
    name = _BAD_CHARS.sub("", name or "")
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > max_len:
        name = name[:max_len].rstrip(" .,-")
    if name.upper() in _RESERVED:
        name = "_" + name
    return name or "untitled"


# --------------------------------------------------------------------------
# Spotify
# --------------------------------------------------------------------------
@dataclass
class Track:
    index: int
    title: str
    artists: list[str]
    duration: int | None      # segundos
    uri: str = ""
    isrc: str = ""
    spotify_id: str = ""
    status: str = "pending"   # pending|ok|skip|failed|no-match
    info: dict = field(default_factory=dict)

    @property
    def artist(self) -> str:
        return ", ".join(self.artists)

    def query(self, suffix: str = "") -> str:
        core = " ".join([self.artists[0] if self.artists else "", clean_title(self.title)])
        q = re.sub(r"\s+", " ", core).strip()
        return f"{q} {suffix}".strip()


@dataclass
class Playlist:
    name: str
    tracks: list[Track]
    url: str
    source: str = "embed"


def _fetch(url: str, headers: dict | None = None, data: bytes | None = None,
           timeout: int = 30) -> str:
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
         "Accept": "text/html,application/json,*/*"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        charset = r.headers.get_content_charset() or "utf-8"
        return r.read().decode(charset, "replace")


SPOTIFY_URL_RE = re.compile(
    r"open\.spotify\.com/(?P<type>track|album|playlist)/(?P<id>[A-Za-z0-9]{22})")


def _tracks_from_embed(entity: dict, url: str) -> Playlist:
    raw = entity.get("trackList") or []
    tracks: list[Track] = []
    for item in raw:
        if item.get("entityType") not in (None, "track"):
            continue
        if item.get("isPlayable") is False:
            continue
        uri = item.get("uri") or ""
        tracks.append(Track(
            index=len(tracks) + 1,
            title=(item.get("title") or "").strip(),
            artists=clean_artists(item.get("subtitle") or ""),
            # Spotify embed ja devolve duracao em ms; yt-dlp devolve segundos.
            duration=round((item.get("duration") or 0) / 1000) or None,
            uri=uri,
            spotify_id=uri.split(":")[-1] if uri else "",
        ))
    name = entity.get("title") or entity.get("name") or "playlist"
    return Playlist(name=name, tracks=tracks, url=url)


def _tracks_from_api(data: dict, url: str, name: str) -> Playlist:
    tracks: list[Track] = []
    for item in data.get("items", []):
        t = item.get("track") or {}
        if not t.get("name") or t.get("is_local"):
            continue
        artists = [a["name"] for a in t.get("artists", []) if a.get("name")]
        tracks.append(Track(
            index=len(tracks) + 1,
            title=t["name"].strip(),
            artists=[strip_accents(a) for a in artists] or ["Unknown"],
            duration=round((t.get("duration_ms") or 0) / 1000) or None,
            uri=t.get("uri") or "",
            isrc=((t.get("external_ids") or {}).get("isrc") or ""),
            spotify_id=t.get("id") or "",
        ))
    return Playlist(name=name, tracks=tracks, url=url, source="api")


def _api_token(client_id: str, client_secret: str) -> str:
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    res = _fetch("https://accounts.spotify.com/api/token", data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {auth}",
    })
    return json.loads(res)["access_token"]


def fetch_playlist(url: str, client_id: str = "", client_secret: str = "",
                   timeout: int = 30) -> Playlist:
    m = SPOTIFY_URL_RE.search(url)
    if not m:
        raise ValueError("URL do Spotify invalida. Use algo como "
                         "https://open.spotify.com/playlist/<id>")
    kind, sid = m.group("type"), m.group("id")

    # 1) API (se houver credenciais) — dados completos e paginados.
    if client_id and client_secret:
        try:
            token = _api_token(client_id, client_secret)
            pages, name, data = [], None, None
            offset = 0
            while True:
                u = (f"https://api.spotify.com/v1/{kind}s/{sid}/tracks"
                     if kind == "playlist" else f"https://api.spotify.com/v1/{kind}s/{sid}")
                q = f"?limit=100&offset={offset}" if kind == "playlist" else ""
                data = json.loads(_fetch(u + q, headers={
                    "Authorization": f"Bearer {token}"}, timeout=timeout))
                if kind == "playlist":
                    name = name or data.get("name")
                    pages.extend(data.get("items", []))
                    if len(data.get("items", [])) < 100:
                        break
                    offset += 100
                else:
                    break
            if kind == "playlist":
                pl = _tracks_from_api({"items": pages}, url, name or "playlist")
            elif kind == "album":
                pl = _tracks_from_api({"items": data.get("tracks", {}).get("items", [])},
                                      url, data.get("name") or "album")
            else:
                t = data
                pl = Playlist(name=t.get("name") or "track", url=url, source="api",
                              tracks=[Track(1, t.get("name", "track"),
                                            [strip_accents(a["name"]) for a in t.get("artists", [])],
                                            round((t.get("duration_ms") or 0) / 1000) or None,
                                            t.get("uri", ""), t.get("id", ""))])
            if pl.tracks:
                log(f"  {bold('Fonte:')} Spotify Web API ({len(pl.tracks)} faixas)")
                return pl
        except Exception as ex:
            log(f"  {dim('API indisponivel, usando embed...')} ({type(ex).__name__})")

    # 2) Embed (sem credenciais)
    html = _fetch(f"https://open.spotify.com/embed/{kind}/{sid}", timeout=timeout)
    m2 = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m2:
        raise RuntimeError("Nao consegui ler a playlist do Spotify. "
                           "Tente novamente ou use --client-id/--client-secret.")
    data = json.loads(m2.group(1))
    entity = data["props"]["pageProps"]["state"]["data"]["entity"]
    pl = _tracks_from_embed(entity, url)
    log(f"  {bold('Fonte:')} pagina embed do Spotify ({len(pl.tracks)} faixas)")
    return pl


# --------------------------------------------------------------------------
# Match de audio
# --------------------------------------------------------------------------
@dataclass
class Candidate:
    video_id: str
    title: str
    duration: int | None
    score: float = 0.0
    url: str = ""


def score_candidate(cand_title: str, cand_dur: int | None,
                    track: Track) -> float:
    ct = norm(cand_title)
    tt = norm(track.title)
    artists = [norm(a) for a in track.artists if norm(a)]

    if not ct:
        return 0.0

    # 1) similaridade do titulo (peso maior)
    s_title = difflib.SequenceMatcher(None, tt, ct).ratio()

    # 2) sobreposicao de tokens do titulo
    tt_tok, ct_tok = set(tt.split()), set(ct.split())
    overlap = (len(tt_tok & ct_tok) / len(tt_tok)) if tt_tok else 0.0

    # 3) artista presente no titulo do candidado
    s_artist = 0.0
    if artists:
        main = max(artists, key=len)
        if main and main in ct:
            s_artist = 1.0
        elif any(a in ct for a in artists):
            s_artist = 0.8
        else:
            for a in artists:
                if difflib.SequenceMatcher(None, a, ct).ratio() > 0.85:
                    s_artist = max(s_artist, 0.5)
                    break

    # 4) duracao (tolerante: versoes do YouTube costumam ter intro/outro)
    s_dur = 0.5
    if cand_dur and track.duration:
        ratio = cand_dur / track.duration
        if 0.97 <= ratio <= 1.03:
            s_dur = 1.0
        elif 0.9 <= ratio <= 1.1:
            s_dur = 0.9
        elif 0.8 <= ratio <= 1.25:
            s_dur = 0.65
        else:
            s_dur = 0.15

    # 5) versao alternativa (live/remix/cover) que o Spotify nao pediu
    extra_versions = version_tags(cand_title) - version_tags(track.title)
    penalty = min(0.14 * len(extra_versions), 0.28)

    total = (0.42 * s_title + 0.18 * overlap + 0.25 * s_artist + 0.15 * s_dur) - penalty
    return round(max(total, 0.0), 4)


def search_track(track: Track, limit: int = 8, ydl_opts: dict | None = None,
                 suffix: str = "") -> list[Candidate]:
    from yt_dlp import YoutubeDL

    q = track.query(suffix)
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "extract_flat": "in_playlist", "ignoreerrors": True,
            "noprogress": True, "socket_timeout": 20}
    opts.update(ydl_opts or {})

    cands: list[Candidate] = []
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{q}", download=False)
    except Exception:
        return cands

    for e in (info or {}).get("entries") or []:
        if not e:
            continue
        vid = e.get("id")
        if not vid:
            continue
        dur = e.get("duration")
        dur = int(dur) if isinstance(dur, (int, float)) else None
        cands.append(Candidate(video_id=vid, title=e.get("title") or "",
                               duration=dur,
                               score=score_candidate(e.get("title") or "", dur, track),
                               url=f"https://www.youtube.com/watch?v={vid}"))

    cands.sort(key=lambda c: c.score, reverse=True)
    return cands


# --------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------
def find_ffmpeg(explicit: str = "") -> str | None:
    if explicit:
        return explicit if Path(explicit).exists() else shutil.which(explicit)
    found = shutil.which("ffmpeg")
    if found:
        return found
    candidates = [
        Path.home() / ".spotdl" / "ffmpeg.exe",
        Path.home() / ".spotdl" / "ffmpeg",
        Path.home() / "bin" / "ffmpeg.exe",
        Path(sys.executable).parent / "ffmpeg.exe",
    ]
    env = os.environ.get("FFMPEG_LOCATION")
    if env:
        candidates.insert(0, Path(env) / "ffmpeg.exe")
        candidates.insert(0, Path(env))
    for c in candidates:
        if c.exists():
            return str(c)
    return None


class _QuietLogger:
    """Silencia o log do yt-dlp: erros 403 sao recuperados pelo retry, entao
    nao devem virar ruido no stderr (o loop de retry decide o que mostrar)."""

    def debug(self, msg, *a, **k):
        pass

    def warning(self, msg, *a, **k):
        pass

    def error(self, msg, *a, **k):
        pass


def build_ytdl_opts(out_dir: Path, fmt: str, quality: str, ffmpeg: str | None,
                    extra: list[str] | None = None) -> dict:
    codec = {"mp3": "mp3", "m4a": "m4a", "opus": "opus", "flac": "flac"}.get(fmt, "mp3")
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "%(title).80B.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": False,
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 3,
        "no_color": True,
        "logger": _QuietLogger(),
    }
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": codec,
            "preferredquality": quality,
        }]
        if codec == "m4a":
            opts["postprocessors"][0]["preferredquality"] = None
    if extra:
        opts["extra_opts"] = extra
    return opts


def download_url(url: str, opts: dict, player_client: str | None = None) -> dict:
    """Baixa uma URL. `player_client` permite trocar o extractor do YouTube."""
    from yt_dlp import YoutubeDL
    o = dict(opts)
    if player_client:
        ea = dict(o.get("extractor_args") or {})
        ya = dict(ea.get("youtube") or {})
        ya["player_client"] = [player_client]
        ea["youtube"] = ya
        o["extractor_args"] = ea
    with YoutubeDL(o) as ydl:
        return ydl.extract_info(url, download=True) or {}


# YouTube devolve 403 (bloqueio temporario do CDN) sob rajadas. Astrategy:
# tentamos outros candidatos ja ranqueados + outro player client + backoff.
CLIENT_FALLBACKS = [None, "android"]


def download_best(cands: list[Candidate], tmp_dir: Path, args: argparse.Namespace,
                  ffmpeg: str | None) -> tuple[Candidate, dict]:
    """Tenta baixar o melhor candidato; se falhar, tenta os proximos."""
    opts = build_ytdl_opts(tmp_dir, args.format, args.quality, ffmpeg)
    last_exc: Exception | None = None
    for attempt, cand in enumerate(cands[:max(1, args.attempts)]):
        for client in CLIENT_FALLBACKS:
            try:
                info = download_url(cand.url, opts, client)
                if info:
                    return cand, info
            except Exception as ex:
                last_exc = ex
                wait = min(args.backoff * (2 ** attempt), 10)
                time.sleep(wait)
    raise last_exc or RuntimeError("falha desconhecida no download")


def fmt_time(sec: float) -> str:
    sec = int(max(sec, 0))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# --------------------------------------------------------------------------
# Orquestracao
# --------------------------------------------------------------------------
def process_track(track: Track, idx: int, total: int, out_dir: Path,
                  args: argparse.Namespace, ffmpeg: str | None,
                  dl_lock: threading.Semaphore) -> Track:
    prefix = f"  [{idx:>2}/{total}]"
    stem_base = sanitize(f"{track.index:02d} - {track.artist} - {clean_title(track.title)}")

    if args.skip_existing:
        for ext in (args.format, "mp3", "m4a", "opus", "flac", "webm"):
            hit = list(out_dir.glob(f"{stem_base}.{ext}"))
            if hit:
                track.status = "skip"
                track.info = {"file": hit[0].name}
                log(f"{prefix} {dim('skip')}  {track.artist} - {track.title}")
                return track

    cands = search_track(track, limit=args.search_limit,
                         ydl_opts={"socket_timeout": 30},
                         suffix=args.query_suffix)
    if not cands:
        track.status = "failed"
        log(f"{prefix} {tint('ERRO', BOLD_RED)}  busca sem resultados: "
            f"{track.artist} - {track.title}")
        return track

    best = cands[0]
    if best.score < args.min_score and not args.force:
        track.status = "no-match"
        track.info = {"best": best.title, "score": best.score,
                      "candidates": [(c.title, c.score) for c in cands[:3]]}
        log(f"{prefix} {tint('SEM MATCH', BOLD_YELLOW)} ({best.score:.2f} < "
            f"{args.min_score:.2f})  {track.artist} - {track.title}")
        log(f"        {dim('top: ' + best.title[:72])}")
        return track

    log(f"{prefix} {tint('match', BOLD_CYAN)} {best.score:.2f}  "
        f"{dim(best.title[:64])}")

    # Cada faixa usa um temporario proprio: sem colisao entre threads e sem
    # o postprocessor do ffmpeg pegar um arquivo que outra thread apagou.
    tmp_dir = out_dir / ".tmp" / f"{os.getpid()}-{track.index}-{uuid.uuid4().hex[:6]}"
    final = out_dir / f"{stem_base}.{args.format if ffmpeg else 'webm'}"
    used = best

    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        # Downloads sao serializados: rajada no CDN do YouTube causa 403.
        with dl_lock:
            used, info = download_best(cands, tmp_dir, args, ffmpeg)

        produced = None
        for e in (args.format, "mp3", "m4a", "opus", "flac", "webm", "mka"):
            hits = list(tmp_dir.glob(f"*.{e}"))
            if hits:
                produced = max(hits, key=lambda p: p.stat().st_mtime)
                break
        if produced is None:
            files = [f for f in tmp_dir.iterdir() if f.is_file()]
            produced = max(files, key=lambda p: p.stat().st_mtime) if files else None
        if produced is None or not produced.exists():
            raise RuntimeError("download terminou sem gerar arquivo")

        if ffmpeg:
            final = out_dir / f"{stem_base}.{args.format}"
        else:
            final = out_dir / f"{stem_base}.{produced.suffix.lstrip('.')}"
        if final.exists():
            final.unlink()
        shutil.move(str(produced), str(final))

        track.status = "ok"
        track.info = {"video_id": used.video_id, "yt_title": used.title,
                      "score": used.score, "file": final.name}
        if used is not best:
            log(f"        {dim('usou candidato alternativo: ' + used.title[:58])}")
        log(f"{prefix} {tint('OK', BOLD_GREEN)}    {dim(final.name[:70])}")
    except Exception as ex:
        track.status = "failed"
        track.info = {"error": f"{type(ex).__name__}: {ex}", "match": best.title}
        log(f"{prefix} {tint('FALHOU', BOLD_RED)}  {track.artist} - {track.title}"
            f"  {dim(str(ex)[:60])}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return track


def print_playlist(pl: Playlist, limit: int | None = None) -> None:
    log(f"  {bold(pl.name)} {dim('(' + str(len(pl.tracks)) + ' faixas)')}\n")
    for t in pl.tracks[:limit] if limit else pl.tracks:
        d = fmt_time(t.duration) if t.duration else "--:--"
        log(f"   {dim(f'{t.index:>3}.')} {t.artist} — {t.title} {dim('[' + d + ']')}")


def write_manifest(pl: Playlist, out_dir: Path, ext: str = "mp3") -> None:
    lines = [f"# {pl.name}", f"# fonte: {pl.url}", ""]
    for t in pl.tracks:
        dur = fmt_time(t.duration) if t.duration else "--:--"
        lines.append(f"{t.index:03d}. {t.artist} - {t.title} [{dur}]")
    (out_dir / "tracklist.txt").write_text("\n".join(lines), encoding="utf-8")

    m3u = ["#EXTM3U"]
    for t in pl.tracks:
        dur = str(t.duration or -1)
        m3u.append(f"#EXTINF:{dur},{t.artist} - {t.title}")
        stem = sanitize(f"{t.index:02d} - {t.artist} - {clean_title(t.title)}")
        real = (t.info.get("file") or f"{stem}.{ext}")
        m3u.append(real)
    (out_dir / "playlist.m3u").write_text("\n".join(m3u), encoding="utf-8")

    bad_file = out_dir / "nao-baixadas.txt"
    bad = [t for t in pl.tracks if t.status in ("failed", "no-match")]
    if bad:
        bad_file.write_text(
            "\n".join(f"{t.index:03d}. {t.artist} - {t.title}  [{t.status}]" for t in bad),
            encoding="utf-8")
    elif bad_file.exists():
        bad_file.unlink()   # run anterior falhou; agora deu tudo certo


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tunegrab",
        description=f"{APP_NAME} {APP_VERSION} — {APP_TAGLINE} (Python 3.9+)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""exemplos:
  tunegrab <url-spotify>                        baixa tudo na pasta da playlist
  tunegrab <url-spotify> -o ~/Music            escolhe a pasta de destino
  tunegrab <url-spotify> --list                so lista, nao baixa
  tunegrab <url-spotify> -f opus -q 160 -c 6   opus 160k, 6 downloads em paralelo
  tunegrab <url-spotify> --dry-run             so mostra o plano de match
""")
    p.add_argument("url", nargs="?", help="link da playlist/album/faixa do Spotify")
    p.add_argument("-o", "--out", default=".", help="pasta base de destino (padrao: atual)")
    p.add_argument("-c", "--concurrency", type=int, default=4,
                   help="buscas simultaneis no YouTube (padrao 4)")
    p.add_argument("--download-slots", type=int, default=2,
                   help="downloads simultaneis; mais que 2 aumenta 403 do YouTube")
    p.add_argument("-f", "--format", default="mp3",
                   choices=["mp3", "m4a", "opus", "flac"], help="formato final")
    p.add_argument("-q", "--quality", default="192", help="bitrate (ex: 128, 192, 320)")
    p.add_argument("--ffmpeg", default="", help="caminho do ffmpeg")
    p.add_argument("--no-ffmpeg", action="store_true",
                   help="nao converte; salva o formato original do YouTube")
    p.add_argument("--search-limit", type=int, default=8, help="candidatos por faixa")
    p.add_argument("--attempts", type=int, default=3,
                   help="quantos candidatos tentar baixar se um falhar (padrao 3)")
    p.add_argument("--backoff", type=float, default=1.5,
                   help="espera base entre tentativas de download (s)")
    p.add_argument("--min-score", type=float, default=0.55,
                   help="score minimo para aceitar o match (padrao 0.55)")
    p.add_argument("--force", action="store_true", help="aceita o melhor candidato sempre")
    p.add_argument("--query-suffix", default="",
                   help="texto extra na busca (ex: 'audio', 'remastered')")
    p.add_argument("--skip-existing", dest="skip_existing",
                   action="store_true", default=True, help="pula arquivos ja baixados")
    p.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    p.add_argument("--list", action="store_true", help="apenas lista a playlist")
    p.add_argument("--dry-run", action="store_true", help="mostra os matches sem baixar")
    p.add_argument("--no-banner", action="store_true", help="nao mostra o banner")
    p.add_argument("--no-anim", action="store_true", help="banner sem animacao")
    p.add_argument("--client-id", default=os.environ.get("SPOTIFY_CLIENT_ID", ""),
                   help="Spotify client id (opcional, usa a API completa)")
    p.add_argument("--client-secret", default=os.environ.get("SPOTIFY_CLIENT_SECRET", ""),
                   help="Spotify client secret (opcional)")
    p.add_argument("--timeout", type=int, default=30, help="timeout de rede (s)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.no_banner:
        print_banner(animate=not args.no_anim)

    t0 = time.time()

    # Sem argumento (duplo-clique no .bat): pergunta o link aqui. Fica no
    # Python porque "set /p" do batch engole espacos/CR e trata EOF mal.
    if not args.url:
        log(f"  {bold('Cole o link da playlist do Spotify:')}")
        log(f"  {dim('(ex: https://open.spotify.com/playlist/5kT0R0PpFjRsThlBwvjfgn)')}")
        try:
            args.url = input("  Link: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not args.url:
            log(f"  {dim('Nenhum link informado. Saindo.')}")
            return 0

    log(f"  {dim('lendo')} {args.url}")
    try:
        pl = fetch_playlist(args.url, args.client_id, args.client_secret, args.timeout)
    except (ValueError, RuntimeError) as ex:
        log(f"  {tint('ERRO', BOLD_RED)} {ex}")
        return 2
    except Exception as ex:
        log(f"  {tint('ERRO', BOLD_RED)} falha de rede: "
            f"{type(ex).__name__}: {ex}")
        return 2

    if not pl.tracks:
        log(f"  {tint('ERRO', BOLD_RED)} playlist vazia.")
        return 3

    print_playlist(pl, limit=None if not args.list else None)

    if args.list:
        log("")
        return 0

    out_dir = Path(args.out).expanduser().resolve() / sanitize(pl.name)
    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"\n  {bold('destino')}  {out_dir}\n")

    ffmpeg = None if args.no_ffmpeg else find_ffmpeg(args.ffmpeg)
    if args.no_ffmpeg:
        log(f"  {dim('ffmpeg: desativado — salvando formato original')}")
    elif ffmpeg:
        log(f"  {dim('ffmpeg: ' + ffmpeg)}")
    else:
        log(f"  {tint('AVISO', BOLD_YELLOW)} ffmpeg nao encontrado: "
            f"vou salvar o audio original do YouTube (sem converter).")

    if args.dry_run:
        log(f"\n  {bold('PLANO DE DOWNLOAD')} {dim('(dry-run)')}\n")
        for t in pl.tracks:
            cands = search_track(t, args.search_limit, suffix=args.query_suffix)
            if not cands:
                log(f"   {dim(f'{t.index:>3}.')} {tint('nenhum resultado', BOLD_RED)} "
                    f"{t.artist} - {t.title}")
                continue
            b = cands[0]
            forte = b.score >= args.min_score
            score_txt = tint(f"{b.score:.2f}",
                             PLAIN_GREEN if forte else PLAIN_YELLOW)
            log(f"   {dim(f'{t.index:>3}.')} [{score_txt} "
                f"{('ok' if forte else 'fraco'):>5}] {dim(b.title[:60])}")
        log("")
        return 0

    dl_lock = threading.Semaphore(args.download_slots)
    workers = max(1, min(args.concurrency, len(pl.tracks)))
    log(f"  {bold('baixando')} {len(pl.tracks)} faixas {dim(f'({workers} buscas em paralelo)')}")

    with futures.ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(process_track, t, i + 1, len(pl.tracks), out_dir,
                            args, ffmpeg, dl_lock): t
                for i, t in enumerate(pl.tracks)}
        for job in futures.as_completed(jobs):
            job.exception()

    ok = sum(1 for t in pl.tracks if t.status == "ok")
    skipped = sum(1 for t in pl.tracks if t.status == "skip")
    nomatch = sum(1 for t in pl.tracks if t.status == "no-match")
    failed = sum(1 for t in pl.tracks if t.status == "failed")
    total_files = len([f for f in out_dir.iterdir()
                       if f.is_file() and f.suffix.lower() in (".mp3", ".m4a", ".opus", ".flac", ".webm")])
    size_mb = sum(f.stat().st_size for f in out_dir.iterdir() if f.is_file()) / 1_048_576

    write_manifest(pl, out_dir, args.format if ffmpeg else "webm")
    tmp = out_dir / ".tmp"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)

    log("")
    log(f"  {_c('─' * 58, *_gradient(0.5))}")
    log(f"  {bold('Resumo')}  {fmt_time(time.time() - t0)}")
    log(f"    {tint('baixadas', BOLD_GREEN)} {ok}"
        f"   {tint('ja existentes', BOLD_CYAN)} {skipped}"
        f"   {tint('sem match', BOLD_YELLOW)} {nomatch}"
        f"   {tint('com erro', BOLD_RED)} {failed}")
    log(f"    {total_files} arquivos · {size_mb:.1f} MB")
    log(f"    {bold(out_dir)}")
    log("")
    return 0 if (failed + nomatch) == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\n  interrompido.")
        sys.exit(130)