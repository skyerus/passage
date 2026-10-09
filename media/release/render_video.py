"""Render Passage's product film from real app screenshots and original motion graphics.

Needs Pillow, NumPy and ffmpeg. Input: narration-paced.wav and Whisper narration.json.
No browser, user archive, credentials or personal reading data are used.
"""
import argparse
import bisect
import json
import math
from pathlib import Path
import subprocess
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
W, H, FPS = 1920, 1080, 30
CREAM, INK, TEAL, MUTED = '#F5F3EB', '#153E38', '#216D63', '#65746E'
WHITE = '#FFFDF6'
STARTS = [0, 5.6, 12.96, 18.56, 29.6, 34.72, 42.16, 51.04, 59.84, 70.9, 76.48]
INTRO = .75
FONT_DIR = Path('/System/Library/Fonts/Supplemental')
FONTS = {}


def font(size, face='sans'):
    key = (size, face)
    if key not in FONTS:
        name = {'sans': 'Arial.ttf', 'bold': 'Arial Bold.ttf', 'serif': 'Georgia.ttf', 'italic': 'Georgia Italic.ttf'}[face]
        path = FONT_DIR / name
        if not path.exists():
            path = Path('/usr/share/fonts/truetype/dejavu') / ('DejaVuSerif.ttf' if face in ('serif','italic') else 'DejaVuSans.ttf')
        FONTS[key] = ImageFont.truetype(str(path), size)
    return FONTS[key]


def text(im, xy, value, size=36, face='sans', color=INK, spacing=16, anchor=None):
    ImageDraw.Draw(im).multiline_text(xy, value, font=font(size, face), fill=color, spacing=spacing, anchor=anchor)


def pill(im, x, y, label, dark=False, size=25):
    f = font(size, 'bold'); d = ImageDraw.Draw(im)
    width = d.textlength(label, font=f) + 44
    d.rounded_rectangle((x,y,x+width,y+size+28),radius=(size+28)//2,fill='#2B5B51' if dark else '#DDEAE2')
    d.text((x+22,y+12),label,font=f,fill=WHITE if dark else TEAL)
    return width


def background(dark=False):
    base = np.array([18,55,48] if dark else [246,244,237], dtype=np.float32)
    yy,xx = np.mgrid[0:H,0:W]
    glow = np.exp(-(((xx-1510)/1050)**2+((yy-200)/820)**2))
    tint = np.array([20,28,19] if dark else [-13,0,-3])
    arr = np.clip(base[None,None,:]+glow[:,:,None]*tint,0,255).astype('uint8')
    return Image.fromarray(arr,'RGB')


LIGHT, DARK = background(), background(True)
SHOTS = {k:Image.open(ROOT/'docs/images'/v).convert('RGB') for k,v in {
    'books':'mac-books.png','quotes':'mac-highlights.png','setup':'mac-setup.png'}.items()}
ICON = Image.open(ROOT/'docs/images/passage-icon.png').convert('RGBA')


def logo(im, x, y, size):
    pic = ICON.resize((size,size),Image.Resampling.LANCZOS)
    im.paste(pic,(int(x),int(y)),pic)


def screenshot(im, name, x, y, width, crop=None):
    pic=SHOTS[name]
    if crop:pic=pic.crop(crop)
    height=round(width*pic.height/pic.width)
    pic=pic.resize((width,height),Image.Resampling.LANCZOS)
    shadow=Image.new('RGBA',(width+60,height+60))
    ImageDraw.Draw(shadow).rounded_rectangle((24,20,width+36,height+40),radius=24,fill=(14,42,32,60))
    shadow=shadow.filter(ImageFilter.GaussianBlur(14))
    im.paste(shadow,(int(x)-30,int(y)-20),shadow)
    mask=Image.new('L',pic.size);ImageDraw.Draw(mask).rounded_rectangle((0,0,width,height),radius=22,fill=255)
    im.paste(pic,(int(x),int(y)),mask)


def device(im, x, y, width, label, highlighted=False, small=False):
    d=ImageDraw.Draw(im);height=int(width*1.43)
    d.rounded_rectangle((x+9,y+15,x+width+9,y+height+15),radius=34,fill='#D3D9CE')
    d.rounded_rectangle((x,y,x+width,y+height),radius=34,fill='#253833')
    d.rounded_rectangle((x+19,y+25,x+width-19,y+height-48),radius=10,fill='#F1EFDE')
    text(im,(x+38,y+54),'CHAPTER ONE',18,'bold',MUTED)
    for row in range(10):
        ly=y+107+row*(height-187)/9
        if highlighted and row in (3,4):d.rounded_rectangle((x+33,ly-4,x+width-34,ly+12),radius=3,fill='#C4D3A2')
        end=x+width-38-(row%3)*16
        d.line((x+39,ly,end,ly),fill='#778277',width=3)
        d.line((x+39,ly+6,end,ly+6),fill='#BDC2B2',width=2)
    d.ellipse((x+width/2-6,y+height-29,x+width/2+6,y+height-17),fill='#829187')
    text(im,(x+width/2,y+height+42),label,25 if small else 29,'bold',anchor='ma')
    return height


def arrow(im, x1,y,x2, progress=1, color=TEAL):
    d=ImageDraw.Draw(im);end=x1+(x2-x1)*progress
    d.line((x1,y,end,y),fill=color,width=4)
    if progress>.95:d.line((end-16,y-11,end,y,end-16,y+11),fill=color,width=4)


def rounded_card(im, box, fill=WHITE):
    ImageDraw.Draw(im).rounded_rectangle(box,radius=28,fill=fill)


def scene(index, elapsed, duration):
    u=min(1,max(0,elapsed/max(duration,.01)))
    enter=1-(1-min(1,elapsed/.7))**3
    dy=int((1-enter)*24)
    dark=index in [2,9,10]
    im=(DARK if dark else LIGHT).copy()
    text(im,(92,52),'PASSAGE',23,'bold',color='#A6C8B8' if dark else TEAL)
    text(im,(1828,52),'READING, TOGETHER.',21,'sans',color='#A6C8B8' if dark else MUTED,anchor='ra')
    if index==0:
        pill(im,104,183,'LOVE YOUR KINDLE?')
        text(im,(100,289+dy),'A second reader.',88,'serif')
        text(im,(100,405+dy),'A fresh start?',88,'serif',TEAL)
        text(im,(106,570),'Your reading should come with you.',32,color=MUTED)
        device(im,1170,251-int(u*8),270,'Kindle',False,True)
        device(im,1520,355-int(u*16),225,'Xteink',True,True)
    elif index==1:
        text(im,(104,164+dy),'Good books. Scattered highlights.',69,'serif')
        device(im,238,330,270,'One reader',True)
        device(im,1420,330,270,'Another reader',False)
        rounded_card(im,(665,405,1250,652))
        text(im,(706,445),'“',104,'serif',TEAL)
        text(im,(800,466),'That line you loved.',35,'serif')
        text(im,(800,531),'On the wrong device.',28,color=MUTED)
        d=ImageDraw.Draw(im)
        for x in range(533,650,24):d.line((x,528,x+12,528),fill='#AAB9AD',width=4)
        for x in range(1274,1400,24):d.line((x,528,x+12,528),fill='#AAB9AD',width=4)
    elif index==2:
        logo(im,808,188+dy,304)
        text(im,(960,551+dy),'Meet Passage.',104,'serif',WHITE,anchor='ma')
        text(im,(960,695),'Your reading, together.',42,color='#B7D2C4',anchor='ma')
        pill(im,716,803,'FREE + OPEN SOURCE',True,28)
    elif index==3:
        text(im,(98,278+dy),'Every passage.\nOne library.',68,'serif',spacing=25)
        text(im,(103,499),'Kindle with KOReader\nCrossPoint readers',30,color=MUTED,spacing=17)
        pill(im,104,655,'COVERS');pill(im,278,655,'DATES');pill(im,428,655,'SEARCH')
        screenshot(im,'books',740-int(u*12),178,1118)
        text(im,(775,946),'Actual Passage app · sample library',20,color=MUTED)
    elif index==4:
        text(im,(102,257+dy),'Find it.\nKeep it.\nShare the words.',64,'serif',spacing=19)
        pill(im,104,596,'COPY QUOTE',size=26)
        pill(im,104,674,'COPY WITH BOOK + AUTHOR',size=22)
        screenshot(im,'quotes',770-int(u*10),195,1070,crop=(510,130,1174,618))
    elif index==5:
        pill(im,104,168,'ALREADY A KINDLE READER?')
        text(im,(104,276+dy),'Bring your\nold highlights.',76,'serif',spacing=25)
        rounded_card(im,(105,544,620,700))
        text(im,(143,579),'My Clippings.txt',36,'bold')
        text(im,(143,637),'Import the archive you already have.',23,color=MUTED)
        text(im,(108,784),'One reader is enough to get started.',28,color=TEAL)
        screenshot(im,'setup',742,240,1110,crop=(0,0,1180,565))
    elif index==6:
        text(im,(960,168+dy),'Continue at the same passage.',70,'serif',anchor='ma')
        device(im,342,330,275,'Kindle · KOReader',True)
        device(im,1285,330,275,'CrossPoint reader',True)
        logo(im,858,395,205)
        arrow(im,670,506,825,min(1,elapsed/1.3))
        arrow(im,1100,506,1235,min(1,max(0,(elapsed-.5)/1.3)))
        text(im,(960,700),'Same EPUB on both readers',30,'bold',anchor='ma')
        text(im,(960,831),'CrossPoint: Upload Local / Apply Remote',28,color=TEAL,anchor='ma')
        text(im,(960,886),'Illustrated sync flow',20,color=MUTED,anchor='ma')
    elif index==7:
        text(im,(104,168+dy),'Your library. Your Mac.',80,'serif')
        screenshot(im,'books',114,340,940)
        rounded_card(im,(1140,337,1806,845))
        for y,num,title,detail in [(389,'01','Stored locally','Your highlights live on your Mac.'),(544,'02','Backed up your way','iCloud Drive or another folder.'),(699,'03','No hosting bill','No GitHub account needed to use it.')]:
            text(im,(1182,y),num,24,'bold',TEAL)
            text(im,(1263,y-6),title,32,'bold')
            text(im,(1263,y+52),detail,23,color=MUTED)
    elif index==8:
        text(im,(104,162+dy),'A little setup. Then keep reading.',67,'serif')
        rounded_card(im,(105,343,928,700))
        rounded_card(im,(974,343,1808,700))
        pill(im,145,388,'KINDLE')
        text(im,(145,482),'Supported jailbreak\n+ KOReader',45,'serif',spacing=20)
        pill(im,1014,388,'CROSSPOINT READER')
        text(im,(1014,482),'Passage firmware\nfor your exact model',45,'serif',spacing=20)
        text(im,(106,790),'For uploads: your Mac must be awake and reachable.',31,color=TEAL)
        text(im,(106,851),'Only importing My Clippings? No jailbreak needed.',26,color=MUTED)
    elif index==9:
        pill(im,108,174,'PUBLIC BETA',True)
        text(im,(105,290+dy),'Free. Open source.\nYours to shape.',85,'serif',WHITE,spacing=25)
        text(im,(111,569),'Download it. Inspect it. Improve it.',36,color='#B7D2C4')
        rounded_card(im,(1120,266,1814,716),fill='#254D43')
        text(im,(1170,319),'MIT-licensed Mac app',34,'bold',WHITE)
        text(im,(1170,411),'Explore the project',28,'bold','#A8D4BB')
        text(im,(1170,464),'github.com/skyerus/\nreader-bridge',37,'sans',WHITE,spacing=15)
        text(im,(1170,612),'Fork it  ·  Build it  ·  Make it yours',24,color='#B7D2C4')
    else:
        logo(im,840,135,240)
        text(im,(960,433+dy),'Keep the words.',88,'serif',WHITE,anchor='ma')
        text(im,(960,545+dy),'Choose the reader.',88,'serif',WHITE,anchor='ma')
        text(im,(960,703),'Passage',52,'serif','#B7D2C4',anchor='ma')
        text(im,(960,818),'github.com/skyerus/reader-bridge',33,'bold',WHITE,anchor='ma')
        text(im,(960,881),'Apple Silicon Mac · Public beta · Link in the description',24,color='#B7D2C4',anchor='ma')
    return im


def stamp(seconds):
    ms=round(seconds*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'


def captions(path):
    rows=json.loads(path.read_text())['transcription'];result=[]
    for row in rows:
        value=row['text'].strip().replace('KO Reader','KOReader').replace('Crosspoint','CrossPoint').replace('MyClippings','My Clippings').replace('Passage as matching',"Passage’s matching")
        item={'start':row['offsets']['from']/1000+INTRO,'end':row['offsets']['to']/1000+INTRO,'text':value}
        if len(value)<14 and result:
            result[-1]['text']+=' '+value;result[-1]['end']=item['end']
        else:result.append(item)
    return result


def music(path, duration):
    sr=48000;n=int(duration*sr);signal=np.zeros(n,dtype=np.float32)
    # Original, quiet, four-chord synth bed; no third-party music samples.
    chords=[(130.81,164.81,196),(110,130.81,164.81),(87.31,110,130.81),(98,123.47,146.83)]
    for start in np.arange(0,duration,4):
        length=min(5.2,duration-start);t=np.arange(int(length*sr))/sr
        env=np.minimum(1,t/1.1)*np.minimum(1,(length-t)/1.6)
        chord=chords[int(start//4)%4];sound=np.zeros(len(t))
        for f in chord:sound+=(np.sin(2*np.pi*f*t)+.22*np.sin(2*np.pi*f*2*t))/3
        idx=int(start*sr);signal[idx:idx+len(t)]+=(sound*env*.035).astype(np.float32)
    for k,start in enumerate(np.arange(.5,duration-2,2)):
        t=np.arange(int(.42*sr))/sr;f=chords[(k//2)%4][k%3]*4
        sound=np.sin(2*np.pi*f*t)*np.exp(-t*9)*np.minimum(1,t/.012)*.025
        idx=int(start*sr);signal[idx:idx+len(t)]+=sound.astype(np.float32)
    signal*=np.minimum(1,np.arange(n)/sr/2)*np.minimum(1,(duration-np.arange(n)/sr)/2)
    stereo=np.stack((signal,np.roll(signal,170)),axis=1)
    with wave.open(str(path),'wb') as out:
        out.setnchannels(2);out.setsampwidth(2);out.setframerate(sr);out.writeframes((stereo*32767).astype('<i2').tobytes())


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--preview',action='store_true');a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    with wave.open(str(a.output/'narration-paced.wav')) as wav:spoken=wav.getnframes()/wav.getframerate()
    duration=spoken+INTRO+2.5;cuts=STARTS+[duration-INTRO]
    caps=captions(a.output/'narration.json')
    (a.output/'Passage-captions.srt').write_text('\n\n'.join(f'{i+1}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}' for i,c in enumerate(caps))+'\n')
    frames=[]
    for i,start in enumerate(STARTS):
        frame=scene(i,2,cuts[i+1]-start);frame.save(a.output/f'scene-{i:02}.jpg',quality=92);frames.append(frame)
    sheet=Image.new('RGB',(W,3*360),CREAM)
    for i,frame in enumerate(frames[:9]):sheet.paste(frame.resize((640,360)),((i%3)*640,(i//3)*360))
    sheet.save(a.output/'contact-sheet.jpg',quality=92)
    thumb=DARK.copy();logo(thumb,116,115,190)
    text(thumb,(108,369),'Your highlights.\nTogether.',106,'serif',WHITE,spacing=30)
    text(thumb,(115,686),'KINDLE + XTEINK',36,'bold','#B7D2C4')
    pill(thumb,114,791,'FREE + OPEN SOURCE',True,29)
    # Device illustration uses a light inset so its screen and labels stay legible.
    rounded_card(thumb,(1150,130,1830,927),fill='#E8ECDD')
    device(thumb,1192,226,260,'Kindle',True,True);device(thumb,1510,351,245,'Xteink',True,True)
    thumb.resize((1280,720),Image.Resampling.LANCZOS).save(a.output/'Passage-thumbnail.jpg',quality=96)
    if a.preview:return
    silent=a.output/'picture.mp4'
    command=['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','-','-an','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(silent)]
    proc=subprocess.Popen(command,stdin=subprocess.PIPE)
    for frame_number in range(math.ceil(duration*FPS)):
        t=frame_number/FPS;local=max(0,t-INTRO);i=max(0,min(10,bisect.bisect_right(STARTS,local)-1));elapsed=local-STARTS[i]
        image=scene(i,elapsed,cuts[i+1]-STARTS[i])
        if i and elapsed<.28:
            previous=scene(i-1,cuts[i]-STARTS[i-1],cuts[i]-STARTS[i-1])
            image=Image.blend(previous,image,elapsed/.28)
        current=next((c for c in caps if c['start']<=t<c['end']),None)
        if current:
            d=ImageDraw.Draw(image);f=font(29);width=d.textlength(current['text'],font=f)+50
            d.rounded_rectangle(((W-width)/2,994,(W+width)/2,1051),radius=16,fill='#163D35')
            d.text((W/2,1007),current['text'],font=f,fill=WHITE,anchor='ma')
        proc.stdin.write(image.tobytes())
        if frame_number%(FPS*10)==0:print(f'Rendered {t:.0f}/{duration:.1f}s',flush=True)
    proc.stdin.close()
    if proc.wait():raise SystemExit('ffmpeg picture render failed')
    music(a.output/'music.wav',duration)
    voice=a.output/'narration-master.wav'
    if not voice.exists():voice=a.output/'narration-paced.wav'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(silent),'-i',str(voice),'-i',str(a.output/'music.wav'),
        '-filter_complex',f'[1:a]loudnorm=I=-16:TP=-1.5:LRA=8,adelay=750|750,apad[v];[2:a]volume=0.6[m];[v][m]amix=inputs=2:normalize=0:duration=longest,alimiter=limit=0.95[a]',
        '-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-b:a','192k','-ar','48000','-t',str(duration),'-movflags','+faststart',str(a.output/'Passage-release-film.mp4')],check=True)
    (a.output/'render.json').write_text(json.dumps({'duration':duration,'width':W,'height':H,'fps':FPS,'screenshots':'Native Passage app with public-domain sample text; docs/images','devices':'Original schematic illustrations','music':'Original synthesized score','narration':'Gemini TTS; see generate_voice.py','captioned':True},indent=2)+'\n')
    print('Finished',a.output/'Passage-release-film.mp4',flush=True)


if __name__=='__main__':main()
