"""Passage film: Blender device models, native UI, a short opening reveal and original sound."""
import argparse
import bisect
from functools import lru_cache
import json
import math
from pathlib import Path
import subprocess
import wave
import numpy as np
from PIL import Image, ImageDraw
import graphics as g

W,H,FPS=1920,1080,30
STARTS=g.STARTS;INTRO=g.INTRO
CREAM='#F4F2E9';MINT='#AED8C6';TEAL='#2B7566';INK='#153D35'
PLATES=None

def ease(x):return 1-(1-min(1,max(0,x)))**3

def background(dark=True):
    y,x=np.mgrid[0:H,0:W];glow=np.exp(-(((x-1330)/880)**2+((y-430)/580)**2))
    c=np.array([8,23,21] if dark else [245,241,229],dtype=float)
    tint=np.array([19,40,31] if dark else [-18,0,-2])
    return Image.fromarray(np.uint8(np.clip(c+glow[:,:,None]*tint,0,255)))

DARK,LIGHT=background(),background(False)

def txt(im,x,y,value,size=46,face='sans',color=CREAM,anchor=None):
    g.text(im,(x,y),value,size,face,color,spacing=15,anchor=anchor)

@lru_cache(maxsize=64)
def plate(name,index):return Image.open(PLATES/name/f'{index:04}.png').convert('RGBA')


def product(im,name,cx,cy,height,reveal=None,angle=0):
    # Only the opening reveal advances the Blender plates. Every later shot
    # holds the same pose instead of looping a turntable behind the narration.
    end=45 if name=='kindle' else 120
    index=end if reveal is None else round(end-45+45*ease(reveal/1.6))
    p=plate(name,index).resize((int(height*.76),int(height)),Image.Resampling.LANCZOS)
    if angle:p=p.rotate(angle,Image.Resampling.BICUBIC,expand=True)
    im.paste(p,(int(cx-p.width/2),int(cy-p.height/2)),p)


def shot(im,name,x,y,width,crop=None):
    # Keep native text and glass at fixed coordinates, with no camera drift.
    g.screenshot(im,name,int(x),int(y),int(width),crop)


def scene(i,e,duration):
    im=(LIGHT if i==5 else DARK).copy()
    if i==0:
        txt(im,91,325,'Kindle +',105,'serif')
        txt(im,91,459,'Xteink',118,'serif',MINT)
        enter=ease(e/1.6)
        product(im,'kindle',1250+180*(1-enter),500,935,reveal=e)
        product(im,'xteink',1620+340*(1-enter),641,596,reveal=e)
    elif i==1:
        product(im,'kindle',330,590,785)
        product(im,'xteink',1590,638,500)
        txt(im,960,405,'Keep your place.',58,'serif',anchor='ma')
        txt(im,960,506,'Save your highlights.',58,'serif',MINT,anchor='ma')
    elif i==2:
        g.logo(im,820,195,280)
        txt(im,960,570,'Passage',112,'serif',anchor='ma')
    elif i==3:
        txt(im,960,111,'Highlights from both readers',64,'serif',anchor='ma')
        # Actual native window: preserve its glass, system colours and type.
        shot(im,'books',90,224,1730,crop=(0,0,2360,974))
    elif i==4:
        txt(im,82,327,'Find a\nhighlight.',54,'serif')
        shot(im,'quotes',405,100,1340)
    elif i==5:
        product(im,'kindle',361,579,800)
        txt(im,777,231,'Import your',83,'serif',INK)
        txt(im,777,335,'Kindle highlights',83,'serif',INK)
        ImageDraw.Draw(im).rounded_rectangle((778,520,1780,678),radius=22,fill='#FFFDF4')
        txt(im,832,560,'My Clippings.txt',52,'serif',INK)
    elif i==6:
        txt(im,960,140,'Pick up where you left off',69,'serif',anchor='ma')
        product(im,'kindle',376,611,749)
        product(im,'xteink',1549,622,477)
        g.logo(im,854,390,214)
        txt(im,960,697,'Upload Local',36,'serif',anchor='ma')
        txt(im,960,755,'Apply Remote',36,'serif',MINT,anchor='ma')
    elif i==7:
        txt(im,101,143,'Keep your library on your Mac',75,'serif')
        shot(im,'books',83,342,1190,crop=(0,0,2360,974))
        txt(im,1355,431,'Back up to\niCloud Drive',44,'serif')
    elif i==8:
        txt(im,960,138,'Connect your readers',67,'serif',anchor='ma')
        product(im,'kindle',470,559,724)
        product(im,'xteink',1445,597,462)
    elif i==9:
        txt(im,92,300,'Free and',110,'serif')
        txt(im,92,442,'open source',110,'serif',MINT)
        g.logo(im,1270,280,370)
    else:
        product(im,'kindle',371,581,843,angle=-3)
        product(im,'xteink',685,665,537,angle=4)
        g.logo(im,1050,242,135)
        txt(im,1038,444,'Passage',105,'serif')
        txt(im,1043,630,'github.com/skyerus/passage',36,'bold')
    return im

def soundtrack(path,duration):
    sr=48000;n=int(duration*sr);a=np.zeros((n,2),np.float32);rng=np.random.default_rng(19)
    def add(start,sound,pan=0):
        j=int(start*sr);count=min(len(sound),n-j)
        if count>0:
            a[j:j+count,0]+=sound[:count]*(1-pan*.4);a[j:j+count,1]+=sound[:count]*(1+pan*.4)
    beat=60/108;chords=[(130.81,164.81,196),(110,130.81,164.81),(87.31,110,130.81),(98,123.47,146.83)]
    for k,start in enumerate(np.arange(0,duration,beat*8)):
        t=np.arange(int(beat*9*sr))/sr;env=np.minimum(1,t/.7)*np.minimum(1,(t[-1]-t)/1.4)
        sound=sum(np.sin(2*np.pi*f*t)+.15*np.sin(4*np.pi*f*t) for f in chords[k%4])/3
        add(start,sound*env*.022,(-1)**k*.5)
    for k,start in enumerate(np.arange(.75,duration-2,beat)):
        t=np.arange(int(.24*sr))/sr
        if k%2==0:add(start,np.sin(2*np.pi*(48*t+18*(1-np.exp(-t*25))/25))*np.exp(-t*25)*.05)
        else:add(start,rng.normal(0,1,len(t))*np.exp(-t*45)*.008,(-1)**k*.5)
        f=chords[(k//8)%4][k%3]*4;add(start,np.sin(2*np.pi*f*t)*np.exp(-t*14)*np.minimum(1,t/.007)*.008,math.sin(k))
    # One opening sweep and a restrained logo chime. Still scenes do not
    # receive repeated whooshes, page clicks or transition sounds.
    t=np.arange(int(.7*sr))/sr
    high=np.r_[0,np.diff(rng.normal(0,1,len(t)))];env=np.sin(np.pi*t/.7)**3
    add(INTRO,high*env*.013,.35)
    for j,f in enumerate([523.25,659.25]):
        t=np.arange(int(.85*sr))/sr
        add(STARTS[2]+INTRO+j*.14,np.sin(2*np.pi*f*t)*np.exp(-t*6)*np.minimum(1,t/.008)*.019,j-.5)
    a*=(np.minimum(1,np.arange(n)/sr/1.5)*np.minimum(1,(duration-np.arange(n)/sr)/2.3))[:,None]
    with wave.open(str(path),'wb') as out:
        out.setnchannels(2);out.setsampwidth(2);out.setframerate(sr);out.writeframes(np.int16(np.clip(a,-1,1)*32767).tobytes())

def main():
    global PLATES
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--plates',type=Path,required=True);p.add_argument('--preview',action='store_true')
    a=p.parse_args();PLATES=a.plates;a.output.mkdir(parents=True,exist_ok=True)
    with wave.open(str(a.output/'narration-paced.wav')) as w:duration=w.getnframes()/w.getframerate()+INTRO+2.5
    if STARTS != sorted(set(STARTS)) or STARTS[-1] >= duration-INTRO-2.5:
        p.error('Scene timings exceed this narration; update STARTS after reviewing the transcript.')
    cuts=STARTS+[duration-INTRO]
    frames=[scene(i,2,cuts[i+1]-s) for i,s in enumerate(STARTS)]
    for i,f in enumerate(frames):f.save(a.output/f'scene-{i:02}.jpg',quality=94)
    sheet=Image.new('RGB',(1920,1440))
    for i,f in enumerate(frames):sheet.paste(f.resize((640,360)),((i%3)*640,(i//3)*360))
    sheet.save(a.output/'contact-sheet.jpg',quality=93)
    thumb=DARK.copy()
    g.logo(thumb,102,103,151)
    txt(thumb,90,334,'Xteink + Kindle',89,'serif')
    txt(thumb,90,480,'Sync with Passage',71,'serif',MINT)
    product(thumb,'kindle',1260,494,990)
    product(thumb,'xteink',1654,658,631)
    thumb.resize((1280,720),Image.Resampling.LANCZOS).save(a.output/'Passage-thumbnail.jpg',quality=96)
    if a.preview:return
    cmd=['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1920x1080','-r',str(FPS),'-i','-','-an','-c:v','libx264','-preset','fast','-crf','17','-pix_fmt','yuv420p','-movflags','+faststart',str(a.output/'picture.mp4')]
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    for frame in range(math.ceil(duration*FPS)):
        t=frame/FPS;local=max(0,t-INTRO);i=max(0,min(10,bisect.bisect_right(STARTS,local)-1));e=local-STARTS[i]
        im=scene(i,e,cuts[i+1]-STARTS[i]) if i==0 and e<1.6 else frames[i]
        if i and e<.20:im=Image.blend(frames[i-1],im,e/.20)
        proc.stdin.write(im.tobytes())
        if frame%(FPS*10)==0:print(f'Rendered {t:.0f}/{duration:.1f}s',flush=True)
    proc.stdin.close()
    if proc.wait():raise SystemExit('Video encoding failed')
    soundtrack(a.output/'music-and-sfx.wav',duration)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(a.output/'picture.mp4'),'-i',str(a.output/'narration-master.wav'),'-i',str(a.output/'music-and-sfx.wav'),
        '-filter_complex','[1:a]loudnorm=I=-16:TP=-2:LRA=8,aformat=channel_layouts=stereo,adelay=750|750,apad[v];[2:a]volume=0.8[m];[v][m]amix=inputs=2:normalize=0:duration=longest,alimiter=limit=0.87[a]',
        '-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-b:a','256k','-ar','48000','-t',str(duration),'-movflags','+faststart',str(a.output/'Passage-release-film.mp4')],check=True)
    (a.output/'render.json').write_text(json.dumps({'duration':duration,'width':W,'height':H,'fps':FPS,'devices':'Blender models of Kindle Paperwhite 11th generation and Xteink X4 Pro; original typeset public-domain pages','screenshots':'Native Passage app; sample library','music_and_sfx':'Original synthesized score, one opening sweep and logo chime','narration':'Gemini TTS','captioned':False,'motion':'1.6-second device reveal only; app and later device shots held still'},indent=2)+'\n')
    print('Finished',a.output/'Passage-release-film.mp4',flush=True)

if __name__=='__main__':main()
