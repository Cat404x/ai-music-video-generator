# AI Music Video Generator

Generate illustrated music videos from local audio files. The program analyzes audio energy, creates a director/editor-assisted storyboard, generates shot keyframes, applies camera motion with FFmpeg, and combines the final video with the original audio.

> **Paid hosted version coming soon.** This open-source version runs locally and requires your own OpenAI API key for AI-generated storyboards and images.

## Features

- Local audio analysis using FFmpeg PCM decoding
- AI director and editor storyboard agents
- AI-generated image keyframes
- Landscape and portrait output
- Push, pull, drift-left, and drift-right camera motions
- Offline gradient preview mode
- Automatic storyboard JSON output
- `.mp4` output with AAC audio

## Requirements

- Python 3.10 or newer
- FFmpeg with `libx264`
- An OpenAI API key for normal AI generation

### Install FFmpeg

**Ubuntu/Debian:**

```bash
sudo apt update
sudo apt install ffmpeg
```

**macOS with Homebrew:**

```bash
brew install ffmpeg
```

**Windows:**

Install FFmpeg, add its `bin` directory to `PATH`, and verify:

```powershell
ffmpeg -version
```

## Installation

```bash
git clone https://github.com/Cat404x/ai-music-video-generator.git
cd ai-music-video-generator
python3 -m venv .venv
```

Activate the environment:

```bash
# macOS/Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Configuration

For AI generation, set your API key:

```bash
# macOS/Linux
export OPENAI_API_KEY="your-api-key"

# Windows PowerShell
$env:OPENAI_API_KEY="your-api-key"
```

A `.env` file is not loaded automatically. Alternatively, use your process manager or shell configuration to set the variable. Keep API keys out of source control.

## Usage

```bash
python music_video.py song.mp3 -o music_video.mp4
```

Example:

```bash
python music_video.py song.mp3 -o night-train.mp4 \
  --brief "A night train crosses a flooded city, neon reflected in the streets, quiet sunrise" \
  --aspect 16:9
```

### Portrait video

```bash
python music_video.py song.mp3 --aspect 9:16 -o vertical.mp4
```

### Generate a short excerpt

```bash
python music_video.py song.mp3 --seconds 20 -o excerpt.mp4
```

### Change shot length

```bash
python music_video.py song.mp3 --shot-seconds 8 -o video.mp4
```

### Replace existing files

```bash
python music_video.py song.mp3 -o video.mp4 --force
```

## Offline preview

Preview mode needs only Python and FFmpeg. It does not call OpenAI or require an API key:

```bash
python music_video.py song.mp3 --preview --seconds 12 -o preview.mp4
```

## Output files

Given `video.mp4`, the program creates:

- `video.mp4`: rendered MP4 containing video and AAC audio
- `video.storyboard.json`: title, style, prompts, motions, frame positions, and timestamps

Temporary files are deleted after rendering.

## Command help

```bash
python music_video.py --help
```

## OpenAI models and costs

You control the text and image models with:

```bash
python music_video.py song.mp3 \
  --text-model gpt-4.1-mini \
  --image-model gpt-image-1
```

AI usage incurs charges from the model provider. A normal render uses two text-generation responses and one image generation per shot.

## Privacy and licensing

- Audio analysis happens locally with FFmpeg.
- Creative briefs and timeline data are sent to the configured text model.
- Visual prompts and style information are sent to the configured image model.
- Review your model provider's terms and the repository license before redistribution.

This project is licensed under the [MIT License](LICENSE).

## Contributing

Issues and pull requests are welcome. Please avoid committing API keys, source audio, generated MP4s, or private credentials.

## Paid version

**Paid hosted version coming soon.** The hosted service will not expose API keys or require local FFmpeg setup for end users.
