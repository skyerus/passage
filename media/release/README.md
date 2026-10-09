# Passage release film

An approximately 65-second, 1920 × 1080 product introduction for YouTube. The film
explains the shared-highlight problem, shows the native Mac app, and introduces
the open-source project. Its device shots use Blender renders of a Kindle
Paperwhite (11th generation) and Xteink X4 Pro. Device poses settle after short,
directed moves. Quote, import, progress and backup illustrations each play once,
with a sound cue tied to the action. Native app shots stay fixed. Selective
supporting lines sit below headings; there are no eyebrow labels above them or
burned-in speech captions.

## Sources

- `narration.txt` and `generate_voice.py`: Gemini TTS script and generator. Read
  `GEMINI_API_KEY` from the environment; never save the key.
- `page_textures.py` and `assets/*-page.png`: properly typeset public-domain
  passages from Jane Austen's *Pride and Prejudice*. Text is mapped onto the
  device screens as a texture, so it stays consistent through camera movement.
- `render_devices.py`: original model geometry, materials, lighting and motion.
- `render_product_film.py` and `graphics.py`: composition, native app screenshots,
  directed motion, typography, thumbnail, original music and action-linked SFX.
- `youtube.md`: suggested title, description and chapters.
- `../../docs/images`: on-screen captures of the released native app in dark
  appearance, including its actual Liquid Glass controls and sidebar.
- `capture/prepare.py`: prepares an isolated, read-only sample session using the
  release executable. It does not recreate views or change the app's theme.
- `capture/provenance.json`: source build and capture details, including cover
  artwork sources. Sample passages and artwork come from public-domain books
  in [Standard Ebooks](https://standardebooks.org/).

The models follow the visible controls and proportions in
[Xteink's official X4 Pro page](https://www.xteink.com/products/xteink-x4-pro-pocket-ereader)
and [Amazon's Paperwhite identification reference](https://www.amazon.com/gp/help/customer/display.html?nodeId=GK33S847NN4V6Y83).
They are original visual reconstructions, not manufacturer CAD or a recording of
a physical sync. No manufacturer endorsement is implied. An AI image was used
as an early composition study; the final device screens and motion are rendered
from deterministic geometry and type, with no AI-generated lettering.

The film describes a shared quote archive, not mirrored in-book underlines.
Its progress sequence shows CrossPoint's manual controls. The narration identifies
the app as a public beta and states the jailbreak, firmware and awake-Mac requirements.

## Rebuild

To refresh the app shots, run:

```sh
python3 media/release/capture/prepare.py --app /Applications/Passage.app \
  --output /tmp/passage-capture.noindex
```

Open the resulting capture app, keep the
Mac's normal appearance, and capture the actual Books, Highlights and Setup
windows. Use the native app's glass rendering; do not use off-screen SwiftUI
snapshots or force light mode. This sample session has a separate bundle
identity and read-only data provider, so it cannot modify the real library.
The checked-in images omit only the macOS title bar and bottom capture edge.
Film framing may zoom into those captures without redrawing their contents.

Use Python 3.12+, Pillow, NumPy, FFmpeg, Blender 5.1 and whisper.cpp with its
`small.en` model. On macOS the renderers use Arial and Georgia; those font files
are not redistributed. The composition helper falls back to DejaVu on Linux;
set the font directory in `page_textures.py` for a non-Mac rebuild.

Set `GEMINI_API_KEY` securely in your environment. Regenerating narration can
incur API charges. This workflow never uploads or publishes a video.

```sh
python3 -m venv /tmp/passage-video-venv
/tmp/passage-video-venv/bin/pip install Pillow numpy
mkdir -p /tmp/passage-film.noindex
/tmp/passage-video-venv/bin/python media/release/generate_voice.py \
  --output /tmp/passage-film.noindex/narration.wav
ffmpeg -i /tmp/passage-film.noindex/narration.wav -ar 16000 \
  /tmp/passage-film.noindex/narration-paced.wav
ffmpeg -i /tmp/passage-film.noindex/narration.wav -ar 48000 \
  /tmp/passage-film.noindex/narration-master.wav
whisper-cli -ng -m /path/to/ggml-small.en.bin \
  -f /tmp/passage-film.noindex/narration-paced.wav -l en -oj \
  -of /tmp/passage-film.noindex/narration -ml 46 -sow
/tmp/passage-video-venv/bin/python media/release/page_textures.py \
  --output media/release/assets
blender --background --factory-startup --python media/release/render_devices.py -- \
  --assets media/release/assets --output /tmp/passage-film.noindex/device-frames --frames 180
/tmp/passage-video-venv/bin/python media/release/render_product_film.py \
  --output /tmp/passage-film.noindex --plates /tmp/passage-film.noindex/device-frames --preview
/tmp/passage-video-venv/bin/python media/release/render_product_film.py \
  --output /tmp/passage-film.noindex --plates /tmp/passage-film.noindex/device-frames
```

Gemini speech generation is nondeterministic. Review its transcript and update
`STARTS` in `graphics.py` when narration changes. Compare the transcript with
the script before exporting. The transcript is an internal timing aid; captions
are left to YouTube. Keep the generated speech at its original speed; pace and
pauses are directed in the TTS request. The voice is Charon with
`gemini-3.8-flash-tts` through `/v1beta/interactions`;
see the [official speech API documentation](https://ai.google.dev/gemini-api/docs/speech-generation)
for current availability and API details.

Output: `Passage-release-film.mp4`, `Passage-thumbnail.jpg`, a render receipt,
and intermediate frames/audio. The MP4 has editorial supporting text but no
speech captions or subtitle track.
Rendered video and API responses stay out of Git. Every sound effect and the
score are synthesized by the renderer, with no third-party music samples.
