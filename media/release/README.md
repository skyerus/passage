# Passage release film

An approximately 84-second, 1920 × 1080 product introduction for YouTube. The film
explains why a shared highlight library helps when moving between a Kindle and a
CrossPoint reader, shows the native Mac app, and introduces the open-source project.

## Sources

- `narration.txt`: the complete spoken script.
- `generate_voice.py`: Gemini TTS generation. The API key is read from the
  `GEMINI_API_KEY` environment variable and never saved.
- `render_video.py`: editable motion graphics, caption placement, original
  synthesized music, thumbnail, and final H.264/AAC export.
- `youtube.md`: suggested title, description, and chapter markers.
- `../../docs/images`: native app captures with sample public-domain text.

Reader drawings are schematic illustrations; they are not footage of an actual
device syncing. The film describes a shared quote archive, not mirrored in-book
underlines. Its progress sequence explicitly shows CrossPoint's manual controls.
It identifies the download as a public beta and states the jailbreak, firmware,
and awake-Mac requirements. Missing historical highlight dates are not invented.

## Rebuild

Use Python 3.12+, Pillow, NumPy, FFmpeg, and whisper.cpp with its `small.en` model.
The renderer uses macOS Arial and Georgia fonts, falling back to DejaVu on Linux.
Font files are not redistributed. Set `GEMINI_API_KEY` securely in your environment
before the first command; generating new narration can incur API charges.

```sh
python3 -m venv /tmp/passage-video-venv
/tmp/passage-video-venv/bin/pip install Pillow numpy
mkdir -p /tmp/passage-film.noindex
/tmp/passage-video-venv/bin/python media/release/generate_voice.py \
  --output /tmp/passage-film.noindex/narration.wav
ffmpeg -i /tmp/passage-film.noindex/narration.wav -af atempo=0.9 -ar 16000 \
  /tmp/passage-film.noindex/narration-paced.wav
ffmpeg -i /tmp/passage-film.noindex/narration.wav -af atempo=0.9 -ar 48000 \
  /tmp/passage-film.noindex/narration-master.wav
whisper-cli -ng -m /path/to/ggml-small.en.bin \
  -f /tmp/passage-film.noindex/narration-paced.wav -l en -oj -osrt \
  -of /tmp/passage-film.noindex/narration -ml 46 -sow
/tmp/passage-video-venv/bin/python media/release/render_video.py \
  --output /tmp/passage-film.noindex --preview
/tmp/passage-video-venv/bin/python media/release/render_video.py \
  --output /tmp/passage-film.noindex
```

Gemini speech generation is nondeterministic. Review the transcript and update
the renderer's `STARTS` timings if narration changes. Verify captions against the
script before publishing. The initial voice is Charon using Gemini 3.8 Flash TTS;
see the [official speech API documentation](https://ai.google.dev/gemini-api/docs/speech-generation)
for current model availability and API details.

The output folder contains `Passage-release-film.mp4`, `Passage-thumbnail.jpg`,
`Passage-captions.srt`, a render receipt, and intermediate audio/images. Captions
are burned into the video; the SRT is also available for accessible YouTube captions.
Rendered media and API responses stay out of Git. This script never uploads or
publishes a video.
