#!/usr/bin/env python3
"""Generate a Hedra Character-3 intro video from an image + TTS script.

Usage:
  python hedra-intro-video.py \
    --image /path/to/avatar.png \
    --script "Hey, I'm Teo..." \
    --voice-id 64f274fb-bbae-4151-8a2f-9aa8794b897f \
    --out /path/to/output.mp4 \
    [--aspect-ratio 1:1] [--resolution 720p] [--duration 20]
"""
import argparse
import logging
import os
import subprocess
import sys
import tempfile
import time

import requests

BASE_URL = "https://api.hedra.com/web-app/public"
CHARACTER_3_MODEL_ID = "d1dd37a3-e39a-4854-a298-6510289f9cf2"
NANO_BANANA_PRO_I2I_MODEL_ID = "c81e401b-6036-4e1f-9165-60eafcee9dd3"


def _which_ffmpeg() -> str:
    """Prefer ffmpeg-full (has drawtext+subtitles). Fall back to default ffmpeg on PATH."""
    for candidate in ("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg", "/usr/local/opt/ffmpeg-full/bin/ffmpeg"):
        if os.path.exists(candidate):
            return candidate
    return "ffmpeg"


def _which_ffprobe() -> str:
    for candidate in ("/opt/homebrew/opt/ffmpeg-full/bin/ffprobe", "/usr/local/opt/ffmpeg-full/bin/ffprobe"):
        if os.path.exists(candidate):
            return candidate
    return "ffprobe"


FFMPEG = _which_ffmpeg()
FFPROBE = _which_ffprobe()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hedra")


def load_api_key() -> str:
    key = os.environ.get("HEDRA_API_KEY")
    if key:
        return key.strip()
    key_file = "/Users/sethward/GIT/Squidgy/.hedra-api-key"
    if os.path.exists(key_file):
        with open(key_file) as f:
            return f.read().strip()
    print("error: HEDRA_API_KEY not set and .hedra-api-key not found", file=sys.stderr)
    sys.exit(1)


def make_session(api_key: str) -> requests.Session:
    s = requests.Session()
    s.headers["x-api-key"] = api_key
    return s


def fetch_image_asset_url(session: requests.Session, asset_id: str) -> str:
    r = session.get(f"{BASE_URL}/assets", params={"type": "image", "ids": asset_id})
    r.raise_for_status()
    items = r.json()
    if not items:
        raise RuntimeError(f"asset {asset_id} not found")
    return items[0]["asset"]["url"]


def generate_baseline_image(
    session: requests.Session,
    reference_path: str,
    prompt: str,
    out_path: str,
    aspect_ratio: str = "16:9",
    resolution: str = "2K",
) -> str:
    ref_id = upload_image(session, reference_path)
    body = {
        "type": "image_to_image",
        "ai_model_id": NANO_BANANA_PRO_I2I_MODEL_ID,
        "start_keyframe_id": ref_id,
        "text_prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
    }
    r = session.post(f"{BASE_URL}/generations", json=body)
    if not r.ok:
        log.error("image gen failed: %s %s", r.status_code, r.text)
        r.raise_for_status()
    data = r.json()
    gen_id = data["id"]
    asset_id = data["asset_id"]
    log.info("image generation started %s (asset %s)", gen_id, asset_id)
    result = wait_for_generation(session, gen_id)
    if result.get("status") != "complete":
        raise RuntimeError(f"image gen failed: {result}")
    url = fetch_image_asset_url(session, asset_id)
    download(url, out_path)
    return out_path


def upload_image(session: requests.Session, path: str) -> str:
    r = session.post(
        f"{BASE_URL}/assets",
        json={"name": os.path.basename(path), "type": "image"},
    )
    r.raise_for_status()
    asset_id = r.json()["id"]
    with open(path, "rb") as f:
        up = session.post(f"{BASE_URL}/assets/{asset_id}/upload", files={"file": f})
    up.raise_for_status()
    log.info("uploaded image %s", asset_id)
    return asset_id


def generate_tts(session: requests.Session, voice_id: str, text: str) -> tuple[str, str]:
    """Returns (asset_id, signed_download_url)."""
    r = session.post(
        f"{BASE_URL}/generations",
        json={"type": "text_to_speech", "voice_id": voice_id, "text": text},
    )
    if not r.ok:
        log.error("tts create failed: %s %s", r.status_code, r.text)
        r.raise_for_status()
    data = r.json()
    gen_id = data["id"]
    log.info("tts generation started %s", gen_id)
    result = wait_for_generation(session, gen_id)
    if result.get("status") != "complete":
        raise RuntimeError(f"tts failed: {result}")
    asset_id = result.get("asset_id") or data.get("asset_id")
    url = result.get("download_url") or result.get("url")
    if not asset_id or not url:
        raise RuntimeError(f"no asset_id/url from tts: {result}")
    log.info("tts audio asset %s", asset_id)
    return asset_id, url


def pad_audio_with_silence(mp3_url: str, tail_ms: int, lead_ms: int = 0) -> str:
    """Download TTS mp3, prepend/append silence, return local path to padded mp3."""
    tmpdir = tempfile.mkdtemp(prefix="hedra_audio_")
    raw = os.path.join(tmpdir, "tts.mp3")
    padded = os.path.join(tmpdir, "tts_padded.mp3")
    with requests.get(mp3_url, stream=True) as r:
        r.raise_for_status()
        with open(raw, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    filt_parts = []
    if lead_ms > 0:
        filt_parts.append(f"adelay={lead_ms}|{lead_ms}")
    if tail_ms > 0:
        filt_parts.append(f"apad=pad_dur={tail_ms}ms")
    af = ",".join(filt_parts) if filt_parts else "anull"
    cmd = [FFMPEG, "-y", "-i", raw, "-af", af, "-c:a", "libmp3lame", "-q:a", "2", padded]
    subprocess.run(cmd, check=True, capture_output=True)
    log.info("padded audio: lead=%dms tail=%dms → %s", lead_ms, tail_ms, padded)
    return padded


def upload_audio(session: requests.Session, path: str) -> str:
    r = session.post(
        f"{BASE_URL}/assets",
        json={"name": os.path.basename(path), "type": "audio"},
    )
    r.raise_for_status()
    asset_id = r.json()["id"]
    with open(path, "rb") as f:
        up = session.post(f"{BASE_URL}/assets/{asset_id}/upload", files={"file": f})
    up.raise_for_status()
    log.info("uploaded padded audio %s", asset_id)
    return asset_id


def trim_video_start(path: str, trim_ms: int) -> None:
    """In-place trim first trim_ms from video using ffmpeg."""
    if trim_ms <= 0:
        return
    tmp = path + ".trim.mp4"
    # Re-encode to get a clean cut on keyframe boundaries
    cmd = [
        FFMPEG, "-y", "-ss", f"{trim_ms/1000:.3f}", "-i", path,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        tmp,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    os.replace(tmp, path)
    log.info("trimmed first %dms", trim_ms)


SQUIDGY_COLORS = {
    "red": "FB252A",
    "magenta": "A61D92",
    "purple": "6017E8",
    "white": "FFFFFF",
}

# Baloo 2 font names as registered in the ttf files
BALOO_FAMILY = "Baloo 2"


def _hex_to_ass_bgr(hex_rgb: str) -> str:
    """Convert RRGGBB → ASS &HBBGGRR& format."""
    hex_rgb = hex_rgb.lstrip("#").upper()
    r, g, b = hex_rgb[0:2], hex_rgb[2:4], hex_rgb[4:6]
    return f"&H00{b}{g}{r}&"


def _ffmpeg_get_duration(path: str) -> float:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def _split_words(text: str) -> list[str]:
    # Keep punctuation attached to the previous word for natural captions
    import re
    tokens = re.findall(r"\S+", text)
    return tokens


def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - h * 3600 - m * 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _distribute_timings(words: list[str], total_s: float, lead_pad_s: float = 0.15) -> list[tuple[float, float, str]]:
    """Weight each word by (len+1) so longer words get proportionally more time.
    Leaves a small lead/tail pad so captions don't butt against cuts."""
    usable = max(total_s - lead_pad_s * 2, 0.1)
    weights = [len(w) + 1 for w in words]
    total_w = sum(weights)
    t = lead_pad_s
    out = []
    for w, wt in zip(words, weights):
        dur = usable * wt / total_w
        out.append((t, t + dur, w))
        t += dur
    return out


def _group_words(timings: list[tuple[float, float, str]], per_group: int) -> list[tuple[float, float, str]]:
    groups = []
    for i in range(0, len(timings), per_group):
        chunk = timings[i : i + per_group]
        start = chunk[0][0]
        end = chunk[-1][1]
        text = " ".join(w for _, _, w in chunk)
        groups.append((start, end, text))
    return groups


def build_ass(
    video_path: str,
    text: str,
    style: str,
    color_hex: str,
    font_dir: str,
    video_w: int,
    video_h: int,
    speech_start_s: float = 0.0,
    speech_end_s: float | None = None,
) -> str:
    """Return path to a temp .ass subtitle file styled for the chosen preset."""
    total = _ffmpeg_get_duration(video_path)
    end = speech_end_s if speech_end_s is not None else total
    speech_dur = max(end - speech_start_s, 0.5)
    words = _split_words(text)
    timings = _distribute_timings(words, speech_dur)
    # shift by speech_start_s so captions begin where speech begins
    timings = [(s + speech_start_s, e + speech_start_s, w) for s, e, w in timings]

    primary = _hex_to_ass_bgr(color_hex)
    white = _hex_to_ass_bgr("FFFFFF")
    black = _hex_to_ass_bgr("000000")

    # Font sizing scaled to video height
    if style == "kinetic":
        fontsize = max(int(video_h * 0.11), 48)
        per_group = 2
        margin_v = int(video_h * 0.5 - fontsize * 0.5)  # centered vertically
    elif style == "karaoke":
        fontsize = max(int(video_h * 0.07), 36)
        per_group = 999  # one block = whole line, then animate per word
        margin_v = int(video_h * 0.08)
    else:  # clean
        fontsize = max(int(video_h * 0.06), 32)
        per_group = 6
        margin_v = int(video_h * 0.08)

    groups = _group_words(timings, per_group) if style != "karaoke" else None

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_w}
PlayResY: {video_h}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{BALOO_FAMILY},{fontsize},{white},{primary},{black},&H80000000&,1,0,0,0,100,100,0,0,1,4,2,{2 if style != 'kinetic' else 5},40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []

    if style == "kinetic":
        # Each group pops in with a small scale bounce
        for start, end, text_g in groups:
            fade = r"{\fad(80,80)\t(0,120,\fscx110\fscy110)\t(120,220,\fscx100\fscy100)\c" + primary + "}"
            events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Main,,0,0,0,,{fade}{text_g}")
    elif style == "karaoke":
        # One dialogue per sentence-ish: split into lines of ~6 words for readability
        lines = _group_words(timings, 6)
        for line_start, line_end, _ in lines:
            # Find the words in this line
            line_words = [(s, e, w) for s, e, w in timings if s >= line_start - 0.01 and e <= line_end + 0.01]
            if not line_words:
                continue
            # Build karaoke tags: {\kf<duration_cs>}word
            parts = []
            for s, e, w in line_words:
                cs = max(int((e - s) * 100), 1)
                parts.append(r"{\kf" + str(cs) + r"}" + w + " ")
            # Highlight color = primary, base = white
            header_tag = r"{\c" + white + r"\2c" + primary + r"\fad(120,120)}"
            events.append(
                f"Dialogue: 0,{_ass_time(line_start)},{_ass_time(line_end)},Main,,0,0,0,,{header_tag}{''.join(parts).rstrip()}"
            )
    else:  # clean
        for start, end, text_g in groups:
            fade = r"{\fad(100,100)}"
            events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Main,,0,0,0,,{fade}{text_g}")

    content = header + "\n".join(events) + "\n"
    out_ass = os.path.join(tempfile.mkdtemp(prefix="hedra_captions_"), "captions.ass")
    with open(out_ass, "w") as f:
        f.write(content)
    return out_ass


def _drawtext_escape(s: str) -> str:
    """Escape text for ffmpeg drawtext filter."""
    return (
        s.replace("\\", "\\\\")
         .replace(":", "\\:")
         .replace("'", "\u2019")  # apostrophes break filter parsing; swap to typographic
         .replace(",", "\\,")
         .replace("%", "\\%")
    )


def _drawtext_escape_path(p: str) -> str:
    return p.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def burn_captions(
    video_path: str,
    text: str,
    style: str,
    color_hex: str,
    font_dir: str,
    speech_start_s: float,
    speech_end_s: float | None,
) -> None:
    """In-place burn captions using ffmpeg's drawtext filter + bundled Baloo 2 font."""
    # Probe dims
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-of", "csv=p=0:s=x", video_path],
        check=True, capture_output=True, text=True,
    )
    w, h = (int(x) for x in out.stdout.strip().split("x"))
    total = _ffmpeg_get_duration(video_path)
    end = speech_end_s if speech_end_s is not None else total
    speech_dur = max(end - speech_start_s, 0.5)
    words = _split_words(text)
    timings = _distribute_timings(words, speech_dur)
    timings = [(s + speech_start_s, e + speech_start_s, w_) for s, e, w_ in timings]

    font_path = os.path.join(font_dir, "Baloo2-ExtraBold.ttf")
    if not os.path.exists(font_path):
        raise RuntimeError(f"font not found: {font_path}")
    font_arg = _drawtext_escape_path(font_path)
    color_rgb = color_hex.lstrip("#")

    if style == "kinetic":
        fontsize = max(int(h * 0.11), 48)
        per_group = 2
        y_expr = f"(h-text_h)/2"
        text_color = f"#{color_rgb}"
        border_w = 6
    elif style == "karaoke":
        # drawtext doesn't natively do per-word highlight within one line, so simulate:
        # show the full phrase in white, then overlay the current word in accent color at its position.
        # Simplification: treat karaoke like 'clean' but with a colored current-word overlay rendered
        # for the brief span of each word. Phrase lines group 6 words.
        fontsize = max(int(h * 0.07), 36)
        per_group = 6
        y_expr = f"h-text_h-{int(h*0.08)}"
        text_color = "white"
        border_w = 4
    else:  # clean
        fontsize = max(int(h * 0.06), 32)
        per_group = 6
        y_expr = f"h-text_h-{int(h*0.08)}"
        text_color = "white"
        border_w = 4

    groups = _group_words(timings, per_group)

    filters = []
    for gs, ge, gt in groups:
        safe_text = _drawtext_escape(gt)
        # fade in/out (0.1s each end) via alpha expression
        alpha_expr = (
            f"if(lt(t,{gs}),0,"
            f"if(lt(t,{gs}+0.1),(t-{gs})/0.1,"
            f"if(lt(t,{ge}-0.1),1,"
            f"if(lt(t,{ge}),({ge}-t)/0.1,0))))"
        )
        # Escape : in alpha expression
        alpha_expr_esc = alpha_expr.replace(":", "\\:").replace(",", "\\,")
        dt = (
            f"drawtext=fontfile='{font_arg}'"
            f":text='{safe_text}'"
            f":fontcolor={text_color}"
            f":fontsize={fontsize}"
            f":borderw={border_w}:bordercolor=black@0.9"
            f":shadowx=0:shadowy=4:shadowcolor=black@0.5"
            f":x=(w-text_w)/2:y={y_expr}"
            f":alpha='{alpha_expr_esc}'"
            f":enable='between(t,{gs-0.1:.3f},{ge+0.1:.3f})'"
        )
        filters.append(dt)

    if style == "karaoke":
        # Overlay: for each word, re-draw it in accent color at its own position.
        # We approximate position by building the phrase and using 'w'-anchored drawtext per word
        # using text_align is nontrivial — instead, pop the current word large and centered above the line.
        pop_fontsize = int(fontsize * 1.05)
        pop_y = f"h-text_h-{int(h*0.08)}-{int(fontsize*0.1)}"
        for ws, we, ww in timings:
            safe = _drawtext_escape(ww)
            dt = (
                f"drawtext=fontfile='{font_arg}'"
                f":text='{safe}'"
                f":fontcolor=#{color_rgb}"
                f":fontsize={pop_fontsize}"
                f":borderw=5:bordercolor=black@0.85"
                f":shadowx=0:shadowy=3:shadowcolor=black@0.5"
                f":x=(w-text_w)/2:y={pop_y}"
                f":enable='between(t,{ws:.3f},{we:.3f})'"
            )
            filters.append(dt)

    vf = ",".join(filters)
    tmp = video_path + ".cap.mp4"
    cmd = [
        FFMPEG, "-y", "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "copy",
        "-movflags", "+faststart",
        tmp,
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        log.error("caption burn failed:\n%s", r.stderr.decode()[-2500:])
        raise RuntimeError("caption burn failed")
    os.replace(tmp, video_path)
    log.info("burned %s captions (Baloo 2 ExtraBold, accent #%s)", style, color_rgb)


def create_video_generation(
    session: requests.Session,
    image_id: str,
    audio_id: str,
    aspect_ratio: str,
    resolution: str,
    duration_s: float | None,
    text_prompt: str,
) -> str:
    body = {
        "type": "video",
        "ai_model_id": CHARACTER_3_MODEL_ID,
        "start_keyframe_id": image_id,
        "audio_id": audio_id,
        "generated_video_inputs": {
            "text_prompt": text_prompt,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
        },
    }
    if duration_s is not None:
        body["generated_video_inputs"]["duration_ms"] = int(duration_s * 1000)
    r = session.post(f"{BASE_URL}/generations", json=body)
    if not r.ok:
        log.error("video create failed: %s %s", r.status_code, r.text)
        r.raise_for_status()
    gen_id = r.json()["id"]
    log.info("video generation started %s", gen_id)
    return gen_id


def wait_for_generation(session: requests.Session, gen_id: str, timeout_s: int = 900) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = session.get(f"{BASE_URL}/generations/{gen_id}/status", timeout=30)
            if r.status_code >= 500:
                log.warning("transient %d on status poll, retrying", r.status_code)
                time.sleep(8)
                continue
            r.raise_for_status()
            data = r.json()
        except (requests.ConnectionError, requests.Timeout) as e:
            log.warning("poll network error (%s), retrying", e)
            time.sleep(8)
            continue
        status = data.get("status")
        log.info("status=%s progress=%s", status, data.get("progress"))
        if status in ("complete", "error"):
            return data
        time.sleep(5)
    raise TimeoutError(f"generation {gen_id} did not complete in {timeout_s}s")


def download(url: str, out_path: str) -> None:
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    log.info("saved %s", out_path)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--image", required=True, help="Source portrait (used as-is, or as reference when --regen-image is set)")
    p.add_argument("--script", required=True, help="Text the avatar will speak")
    p.add_argument("--voice-id", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--regen-image", action="store_true", help="Regenerate the source portrait via Nano Banana Pro I2I before rendering video")
    p.add_argument("--image-prompt", default=None, help="Prompt for --regen-image")
    p.add_argument("--regen-out", default=None, help="Where to save the regenerated portrait (defaults to sibling of --image with _v2 suffix)")
    p.add_argument("--aspect-ratio", default="1:1", choices=["1:1", "16:9", "9:16"])
    p.add_argument("--resolution", default="720p", choices=["540p", "720p", "1080p"])
    p.add_argument("--duration", type=float, default=None, help="Seconds")
    p.add_argument(
        "--text-prompt",
        default="A person speaking directly to camera with warm, friendly energy.",
    )
    p.add_argument("--tail-silence-ms", type=int, default=1500, help="Silence appended after the script so the avatar settles to a resting face before the cut. Set 0 to disable.")
    p.add_argument("--lead-silence-ms", type=int, default=0, help="Silence prepended before the script. Usually unnecessary if --trim-start-ms is used.")
    p.add_argument("--trim-start-ms", type=int, default=400, help="Trim this many ms off the video start to drop the initial soft/blurred frame. Set 0 to disable.")
    p.add_argument("--captions", action="store_true", help="Burn captions into the video (Baloo 2 font, Squidgy palette).")
    p.add_argument("--caption-style", default="clean", choices=["clean", "kinetic", "karaoke"], help="Caption preset.")
    p.add_argument("--caption-color", default="magenta", help="Accent color: red|magenta|purple|white or RRGGBB hex.")
    args = p.parse_args()

    api_key = load_api_key()
    session = make_session(api_key)

    source_image = args.image
    if args.regen_image:
        if not args.image_prompt:
            print("error: --image-prompt required with --regen-image", file=sys.stderr)
            sys.exit(1)
        if args.regen_out:
            regen_out = args.regen_out
        else:
            base, ext = os.path.splitext(args.image)
            regen_out = f"{base}_v2.png"
        source_image = generate_baseline_image(
            session,
            reference_path=args.image,
            prompt=args.image_prompt,
            out_path=regen_out,
        )
        log.info("using regenerated source %s", source_image)

    image_id = upload_image(session, source_image)
    tts_asset_id, tts_url = generate_tts(session, args.voice_id, args.script)
    if args.tail_silence_ms > 0 or args.lead_silence_ms > 0:
        padded_path = pad_audio_with_silence(tts_url, args.tail_silence_ms, args.lead_silence_ms)
        audio_id = upload_audio(session, padded_path)
    else:
        audio_id = tts_asset_id
    gen_id = create_video_generation(
        session,
        image_id=image_id,
        audio_id=audio_id,
        aspect_ratio=args.aspect_ratio,
        resolution=args.resolution,
        duration_s=args.duration,
        text_prompt=args.text_prompt,
    )
    result = wait_for_generation(session, gen_id)

    if result.get("status") != "complete":
        log.error("generation failed: %s", result.get("error_message") or result)
        sys.exit(2)

    url = result.get("download_url") or result.get("url")
    if not url:
        log.error("no download url in response: %s", result)
        sys.exit(3)
    download(url, args.out)
    if args.trim_start_ms > 0:
        trim_video_start(args.out, args.trim_start_ms)
    if args.captions:
        color_hex = SQUIDGY_COLORS.get(args.caption_color.lower(), args.caption_color.lstrip("#"))
        font_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "assets", "fonts"))
        # Speech starts after any lead silence minus the trim we already applied
        speech_start = max((args.lead_silence_ms - args.trim_start_ms) / 1000.0, 0.0)
        # Speech ends where audio stops speaking — total duration minus tail silence
        total_dur = _ffmpeg_get_duration(args.out)
        speech_end = max(total_dur - args.tail_silence_ms / 1000.0, speech_start + 0.5)
        burn_captions(args.out, args.script, args.caption_style, color_hex, font_dir, speech_start, speech_end)
    print(args.out)


if __name__ == "__main__":
    main()
