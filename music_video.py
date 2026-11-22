#!/usr/bin/env python3
"""Generate an illustrated music video from a local audio file."""

import argparse
import base64
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from array import array

FPS = 24
SAMPLE_RATE = 8000
WINDOW = 400
MOTIONS = ("push", "pull", "drift-left", "drift-right")


def ffmpeg(*args, cwd=None, capture=False):
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args],
        cwd=cwd,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise RuntimeError(
            result.stderr.decode(errors="replace").strip() or "FFmpeg failed"
        )
    return result.stdout


def analyze(source, seconds, shot_length):
    limit = ["-t", str(seconds)] if seconds is not None else []
    pcm = ffmpeg(
        "-i", str(source), "-map", "0:a:0", *limit, "-ac", "1", "-ar",
        str(SAMPLE_RATE), "-f", "s16le", "-", capture=True,
    )
    samples = array("h", pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        raise ValueError("The input audio is empty.")

    energy = []
    for start in range(0, len(samples), WINDOW):
        window = samples[start:start + WINDOW]
        energy.append(math.sqrt(sum(sample * sample for sample in window) / len(window)))

    rises = [0.0] + [max(0.0, b - a) for a, b in zip(energy, energy[1:])]
    duration = len(samples) / SAMPLE_RATE
    frames = max(1, math.ceil(duration * FPS))
    shot_count = min(48, max(1, round(duration / shot_length)))
    cuts = [0]

    for index in range(1, shot_count):
        target = index * duration / shot_count
        radius = min(0.75, duration / shot_count / 4)
        first = max(1, math.ceil((target - radius) * SAMPLE_RATE / WINDOW))
        last = min(len(rises), math.floor((target + radius) * SAMPLE_RATE / WINDOW) + 1)
        strongest = max(
            range(first, last),
            key=lambda j: (rises[j], -abs(j * WINDOW / SAMPLE_RATE - target)),
            default=0,
        )
        cut = strongest * WINDOW / SAMPLE_RATE if rises[strongest] else target
        frame = round(cut * FPS)
        if cuts[-1] < frame < frames:
            cuts.append(frame)

    cuts.append(frames)
    peak = max(energy) or 1
    timeline = []
    for index, (start, end) in enumerate(zip(cuts, cuts[1:]), 1):
        first = int(start / FPS * SAMPLE_RATE / WINDOW)
        last = math.ceil(end / FPS * SAMPLE_RATE / WINDOW)
        section = energy[first:last] or [0]
        timeline.append({
            "shot": index,
            "start_frame": start,
            "end_frame": end,
            "start_seconds": round(start / FPS, 3),
            "end_seconds": round(min(duration, end / FPS), 3),
            "relative_energy": round(sum(section) / (len(section) * peak), 3),
        })

    return duration, timeline


SHOT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "visual_style": {"type": "string"},
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "motion": {"type": "string", "enum": list(MOTIONS)},
                },
                "required": ["prompt", "motion"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "visual_style", "shots"],
    "additionalProperties": False,
}


class StoryAgent:
    def __init__(self, client, model, name, instructions):
        self.client = client
        self.model = model
        self.name = name
        self.instructions = instructions

    def run(self, context):
        response = self.client.responses.create(
            model=self.model,
            instructions=self.instructions,
            input=json.dumps(context, ensure_ascii=False),
            text={"format": {
                "type": "json_schema",
                "name": self.name,
                "strict": True,
                "schema": SHOT_SCHEMA,
            }},
        )
        if not response.output_text:
            raise RuntimeError(f"The {self.name} agent returned no storyboard.")
        return json.loads(response.output_text)


class VisualAgent:
    def __init__(self, client, model, portrait):
        self.client = client
        self.model = model
        self.size = "1024x1536" if portrait else "1536x1024"

    def run(self, style, shot, path):
        result = self.client.images.generate(
            model=self.model,
            size=self.size,
            quality="medium",
            output_format="png",
            prompt=(
                f"Create one cinematic music video keyframe. Shared visual direction: {style}\n"
                f"Shot: {shot['prompt']}\n"
                "Full-bleed composition. Keep essential subjects in the central 75% for a crop "
                "and camera movement. No captions, typography, borders, or watermarks."
            ),
        )
        if not result.data or not result.data[0].b64_json:
            raise RuntimeError("The image model returned no image.")
        path.write_bytes(base64.b64decode(result.data[0].b64_json, validate=True))


def make_storyboard(args, timeline, client):
    if args.preview:
        return {
            "title": "Abstract preview",
            "visual_style": "Animated color gradients",
            "shots": [
                {"prompt": f"Abstract gradient {index + 1}", "motion": MOTIONS[index % len(MOTIONS)]}
                for index in range(len(timeline))
            ],
        }

    context = {
        "creative_brief": args.brief,
        "aspect_ratio": args.aspect,
        "timeline": timeline,
    }
    director = StoryAgent(
        client, args.text_model, "director",
        "Direct a music video from the creative brief and measured audio energy. "
        "Return exactly one storyboard shot per timeline row, in the original order. "
        "Create a coherent visual arc and use the energy data to vary composition and motion. "
        "Each prompt must be a standalone description for a still-image model. Describe "
        "recurring subjects consistently. Choose one camera move per shot.",
    )
    editor = StoryAgent(
        client, args.text_model, "editor",
        "Revise the director's storyboard against the creative brief and timeline. "
        "Return a complete storyboard with exactly one shot per timeline row in the original "
        "order. Strengthen visual continuity, improve shot variety, and keep each prompt "
        "self-contained. Choose camera moves suited to each shot's duration and energy.",
    )

    print("Director is drafting the storyboard.", flush=True)
    draft = director.run(context)
    print("Editor is reviewing the storyboard.", flush=True)
    storyboard = editor.run({**context, "director_draft": draft})
    if len(storyboard["shots"]) != len(timeline):
        storyboard = editor.run({
            **context,
            "director_draft": draft,
            "revision": f"Return exactly {len(timeline)} shots.",
        })
    if len(storyboard["shots"]) != len(timeline):
        raise RuntimeError("The editor returned the wrong number of shots.")
    return storyboard


def preview_frame(path, index, width, height):
    colors = ("0x214D71", "0xDD7955", "0x664084", "0x2F9A83", "0xE9BD79")
    first = colors[index % len(colors)]
    second = colors[(index + 2) % len(colors)]
    ffmpeg(
        "-f", "lavfi", "-i",
        f"gradients=s={width}x{height}:c0={first}:c1={second}:seed={index}",
        "-frames:v", "1", "-threads", "1", str(path),
    )


def render_shot(image, clip, shot, width, height):
    count = shot["end_frame"] - shot["start_frame"]
    progress = f"on/{max(1, count - 1)}"
    zoom = {
        "push": f"1.01+0.11*({progress})",
        "pull": f"1.12-0.11*({progress})",
        "drift-left": "1.12",
        "drift-right": "1.12",
    }[shot["motion"]]
    horizontal = {
        "drift-left": f"1-({progress})",
        "drift-right": progress,
    }.get(shot["motion"], "0.5")
    canvas = f"{width * 2}:{height * 2}"
    filters = (
        f"scale={canvas}:force_original_aspect_ratio=increase,"
        f"crop={canvas},setsar=1,"
        f"zoompan=z='{zoom}':x='(iw-iw/zoom)*({horizontal})':y='(ih-ih/zoom)/2':"
        f"d={count}:s={width}x{height}:fps={FPS}"
    )
    ffmpeg(
        "-filter_threads", "2", "-i", str(image), "-vf", filters, "-frames:v", str(count),
        "-an", "-c:v", "libx264", "-threads", "2", "-preset", "fast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-video_track_timescale", str(FPS * 1000), str(clip),
    )


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path, help="Local audio file")
    parser.add_argument("-o", "--output", type=Path, default=Path("music_video.mp4"))
    parser.add_argument("--brief", default="Surreal landscapes that evolve from dusk to dawn.")
    parser.add_argument("--aspect", choices=("16:9", "9:16"), default="16:9")
    parser.add_argument("--shot-seconds", type=float, default=5)
    parser.add_argument("--seconds", type=float, help="Use only the first N seconds")
    parser.add_argument("--text-model", default="gpt-4.1-mini")
    parser.add_argument("--image-model", default="gpt-image-1")
    parser.add_argument("--preview", action="store_true", help="Render local gradients without API calls")
    parser.add_argument("--force", action="store_true", help="Replace an existing MP4 and storyboard")
    args = parser.parse_args()

    for value, flag in ((args.seconds, "--seconds"), (args.shot_seconds, "--shot-seconds")):
        if value is not None and (not math.isfinite(value) or value <= 0):
            parser.error(f"{flag} must be a finite positive number")
    if args.shot_seconds < 1:
        parser.error("--shot-seconds must be at least 1")
    if args.output.suffix.lower() != ".mp4":
        parser.error("--output must have an .mp4 extension")
    return args


def main():
    args = parse_args()
    source = args.audio.resolve()
    output = args.output.absolute()
    storyboard_path = output.with_suffix(".storyboard.json")

    if not source.is_file():
        raise ValueError(f"Audio file not found: {source}")
    if source in (output.resolve(), storyboard_path.resolve()):
        raise ValueError("Choose an output path different from the audio input.")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("Install FFmpeg and add it to PATH.")
    for path in (output, storyboard_path):
        if (path.exists() or path.is_symlink()) and (not args.force or path.is_dir()):
            raise ValueError(f"Output already exists: {path}")

    client = None
    if not args.preview:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("Set OPENAI_API_KEY for AI generation, or use --preview.")
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("Install the OpenAI SDK with pip install -r requirements.txt.") from None
        client = OpenAI(timeout=180.0)

    duration, timeline = analyze(source, args.seconds, args.shot_seconds)
    print(f"Analyzed {duration:.2f} seconds of audio across {len(timeline)} shots.", flush=True)
    storyboard = make_storyboard(args, timeline, client)
    storyboard["shots"] = [
        {**timing, **shot} for timing, shot in zip(timeline, storyboard["shots"])
    ]
    storyboard.update(aspect=args.aspect, fps=FPS, duration_seconds=duration, preview=args.preview)

    portrait = args.aspect == "9:16"
    width, height = (720, 1280) if portrait else (1280, 720)
    artist = None if args.preview else VisualAgent(client, args.image_model, portrait)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".music-video-", dir=output.parent) as directory:
        work = Path(directory)
        names = []

        for index, shot in enumerate(storyboard["shots"], 1):
            print(f"Rendering shot {index}/{len(timeline)}.", flush=True)
            image = work / "frame.png"
            clip = work / f"shot-{index:03d}.mp4"
            if artist is None:
                preview_frame(image, index, width, height)
            else:
                artist.run(storyboard["visual_style"], shot, image)
            render_shot(image, clip, shot, width, height)

            # Use absolute frame positions when rounding concat timestamps to microseconds.
            start_us = round(shot["start_frame"] * 1_000_000 / FPS)
            end_us = round(shot["end_frame"] * 1_000_000 / FPS)
            names.append(f"file '{clip.name}'\nduration {(end_us - start_us) / 1_000_000:.6f}\n")

        (work / "shots.txt").write_text("".join(names), encoding="utf-8")
        ffmpeg(
            "-f", "concat", "-safe", "1", "-i", "shots.txt", "-i", str(source),
            "-map", "0:v:0", "-map", "1:a:0", "-t", f"{duration:.9f}",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            "video.mp4", cwd=work,
        )
        (work / "storyboard.json").write_text(
            json.dumps(storyboard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        (work / "video.mp4").replace(output)
        (work / "storyboard.json").replace(storyboard_path)

    print(f"Video saved to {output}\nStoryboard saved to {storyboard_path}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        sys.exit(f"Error: {error}")
    except KeyboardInterrupt:
        sys.exit("Cancelled.")
    except Exception as error:
        if type(error).__module__.startswith("openai"):
            sys.exit(f"OpenAI request failed: {error}")
        raise
