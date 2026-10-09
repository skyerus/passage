"""Generate the release narration with Gemini; API key stays in the environment."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import ssl
import urllib.error
import urllib.request
import wave


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', default='gemini-3.8-flash-tts')
    parser.add_argument('--voice', default='Charon')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; choose a new path to avoid a duplicate paid request.')
    key = os.environ.get('GEMINI_API_KEY')
    if not key:
        parser.error('Set GEMINI_API_KEY in your environment; never commit it.')
    script = Path(__file__).with_name('narration.txt').read_text().strip()
    style = ('Natural British English, explaining a useful tool to a friend. '
             'Calm and conversational, with ordinary speech inflection rather than an advertising voice. '
             'About 155 words per minute, short natural pauses, never shouty or breathless. '
             'Pronounce Passage as the ordinary English word, Xteink as ex-tee-ink, KOReader as kay-oh reader, and EPUB as ee-pub. '
             'Read only the supplied transcript, exactly once.')
    body = {'model': args.model, 'input': [{'type': 'user_input', 'content': [{
        'type': 'text', 'text': script,
        'annotations': [{'type': 'speech_metadata', 'style': style}]}]}],
        'response_format': {'type': 'audio'},
        'generation_config': {'speech_config': [{'voice': args.voice}]}}
    context = ssl.create_default_context()
    if Path('/etc/ssl/cert.pem').is_file():
        context.load_verify_locations('/etc/ssl/cert.pem')
    request = urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/interactions',
        data=json.dumps(body).encode(), headers={'x-goog-api-key': key, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, context=context, timeout=180) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f'Gemini returned HTTP {exc.code}: {exc.read().decode()[:1000]}') from None
    blocks = [part for step in result.get('steps', []) if step.get('type') == 'model_output'
              for part in step.get('content', []) if part.get('type') == 'audio']
    if not blocks and result.get('output_audio'):
        blocks = [result['output_audio']]
    if not blocks:
        raise SystemExit('No audio returned. Response keys: ' + ', '.join(result))
    data = base64.b64decode(blocks[-1]['data'], validate=True)
    if not data.startswith(b'RIFF'):
        raise SystemExit('Expected WAV output; refusing to save an unknown audio format.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    with wave.open(str(args.output)) as audio:
        duration = audio.getnframes() / audio.getframerate()
    receipt = {'model': args.model, 'voice': args.voice, 'duration_seconds': duration,
        'script_sha256': hashlib.sha256(script.encode()).hexdigest(),
        'audio_sha256': hashlib.sha256(data).hexdigest(),
        'usage': result.get('usage', {}), 'api_documentation': 'https://ai.google.dev/gemini-api/docs/speech-generation'}
    args.output.with_suffix('.voice.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
