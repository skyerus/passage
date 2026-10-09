"""Prepare an isolated capture app using the unchanged release executable.

Only the data provider and bundle identity differ. Native SwiftUI views, system
appearance and glass rendering are untouched. The sample helper is read-only.
Launch the resulting app normally, then capture its on-screen window.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

BOOKS = [
    ('pride', 'Pride and Prejudice', 'Jane Austen', 'jane-austen_pride-and-prejudice', 'It is a truth universally acknowledged, that a single man in possession of a good fortune, must be in want of a wife.'),
    ('moby', 'Moby-Dick', 'Herman Melville', 'herman-melville_moby-dick', 'Call me Ishmael.'),
    ('alice', 'Alice’s Adventures in Wonderland', 'Lewis Carroll', 'lewis-carroll_alices-adventures-in-wonderland', 'Curiouser and curiouser!'),
    ('jane', 'Jane Eyre', 'Charlotte Brontë', 'charlotte-bronte_jane-eyre', 'I am no bird; and no net ensnares me: I am a free human being with an independent will.'),
    ('walden', 'Walden', 'Henry David Thoreau', 'henry-david-thoreau_walden', 'I went to the woods because I wished to live deliberately.'),
    ('frankenstein', 'Frankenstein', 'Mary Shelley', 'mary-shelley_frankenstein', 'Beware; for I am fearless, and therefore powerful.'),
    ('dorian', 'The Picture of Dorian Gray', 'Oscar Wilde', 'oscar-wilde_the-picture-of-dorian-gray', 'The only way to get rid of a temptation is to yield to it.'),
    ('garden', 'The Secret Garden', 'Frances Hodgson Burnett', 'frances-hodgson-burnett_the-secret-garden', 'Where you tend a rose, my lad, a thistle cannot grow.'),
]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--app',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); out=args.output.resolve(); out.mkdir(parents=True,exist_ok=True)
    covers=out/'covers'; covers.mkdir(exist_ok=True)
    for ident,title,author,repository,quote in BOOKS:
        path=covers/f'{ident}.jpg'
        if not path.exists():
            subprocess.run(['curl','-fL','--retry','2','--silent','--show-error',f'https://raw.githubusercontent.com/standardebooks/{repository}/master/images/cover.jpg','-o',str(path)],check=True)
    highlights=[]; books=[]
    for i,(ident,title,author,repository,quote) in enumerate(BOOKS):
        cover=str(covers/f'{ident}.jpg'); date=f'2026-09-{24-i:02d}'
        highlights.append(dict(id=ident,title=title,author=author,text=quote,source='koreader' if i%2==0 else 'crosspoint',created_at=date,book_id=ident,cover_path=cover))
        books.append(dict(id=ident,title=title,author=author,count=1,cover_path=cover,latest_highlight_at=1790251200-i*86400))
    status=dict(service=dict(installed=True,healthy=True,port=8084,mode='local',archive='',pending_backup=0),kindle=dict(paired=True,connected=False,mount=''),xteink=dict(paired=True,firmware_staged=True,url='',model='xteink_x4_pro'),mounts=[],highlights=highlights,highlight_count=len(highlights),books=books,progress_verified=False,endpoint='http://reader.local:8084',addresses=[],warnings=[],library=dict(installed=False,port=8083,books=''),cloud_backup=dict(enabled=True,provider='icloud',folder=str(out/'sample-backup'),saved_at='2026-09-24T12:00:00Z',error='',cloud_upload_verified=False),highlights_order='recent',highlights_undated=0)
    (out/'sample-status.json').write_text(json.dumps(status,indent=2)+'\n')
    helper=out/'sample_backend.py'
    helper.write_text('''import json, sys\nfrom pathlib import Path\nrequest=json.load(sys.stdin)\nstatus=json.loads((Path(__file__).parent/'sample-status.json').read_text())\n# The capture process never contacts readers, services or the user archive.\nif request.get('command') not in ('status','search_highlights'):\n print(json.dumps({'ok':False,'error':'Sample capture is read-only.'}))\nelse:\n print(json.dumps({'ok':True,'data':status}))\n''')
    bundle=out/'Passage Film Capture.app'; mac=bundle/'Contents/MacOS'; resources=bundle/'Contents/Resources'
    mac.mkdir(parents=True,exist_ok=True); resources.mkdir(parents=True,exist_ok=True)
    source=args.app/'Contents/MacOS/ReaderBridge'
    shutil.copy2(source,mac/'ReaderBridge')
    plist=plistlib.loads((args.app/'Contents/Info.plist').read_bytes())
    plist.update(CFBundleIdentifier='com.passage.filmcapture',CFBundleDisplayName='Passage Film Capture',CFBundleName='Passage Film Capture',LSEnvironment={'READER_BRIDGE_PYTHON':sys.executable,'READER_BRIDGE_BACKEND':str(helper),'READER_BRIDGE_APP_DIR':str(out/'isolated-data')})
    (bundle/'Contents/Info.plist').write_bytes(plistlib.dumps(plist))
    for icon in (args.app/'Contents/Resources').glob('*.icns'):shutil.copy2(icon,resources/icon.name)
    binary_sha=hashlib.sha256(source.read_bytes()).hexdigest()
    assert hashlib.sha256((mac/'ReaderBridge').read_bytes()).hexdigest()==binary_sha
    # Ad-hoc sign the local capture bundle after assigning its isolated identity.
    subprocess.run(['codesign','--force','--sign','-','--deep',str(bundle)],check=True)
    (out/'capture-provenance.json').write_text(json.dumps({'release_version':plist['CFBundleShortVersionString'],'release_build':plist['CFBundleVersion'],'original_executable_sha256':binary_sha,'native_views_modified':False,'appearance':'System appearance; no override','capture_method':'On-screen native app window via CUA','data':'Read-only sample backend with public-domain passages','cover_sources':[f'https://github.com/standardebooks/{b[3]}' for b in BOOKS]},indent=2)+'\n')
    print(bundle)
if __name__=='__main__':main()
