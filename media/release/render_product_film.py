"""Passage film: Blender device models, native UI, directed device motion, supporting text and action-linked sound."""
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

def beat(t,start,length=1):
    return ease((t-start)/length)


def mix(a,b,u):return a+(b-a)*u


@lru_cache(maxsize=180)
def plate(name,index):return Image.open(PLATES/name/f'{index:04}.png').convert('RGBA')


@lru_cache(maxsize=256)
def product_plate(name,index,height):
    return plate(name,index).resize((round(height*.76),height),Image.Resampling.LANCZOS)


def product(im,name,cx,cy,height,pose=45):
    # Advance a finite interval of the Blender pose sequence, then hold.
    # No time-modulo turntables, floating sine waves or perpetual camera drift.
    pic=product_plate(name,round(pose),round(height))
    im.paste(pic,(round(cx-pic.width/2),round(cy-pic.height/2)),pic)


@lru_cache(maxsize=8)
def app_frame(name,x,y,width,crop):
    im=DARK.copy()
    g.screenshot(im,name,x,y,width,crop)
    return im


def sub(im,x,y,value,size=30,dark=True,anchor=None):
    txt(im,x,y,value,size,color='#B5CEC1' if dark else '#416255',anchor=anchor)


def reveal_text(im,x,y,value,t,start,size=30,color=MINT,face='sans',anchor=None):
    alpha=beat(t,start,.4)
    if alpha<=0:return
    overlay=Image.new('RGBA',im.size)
    txt(overlay,x,y,value,size,face,color,anchor)
    overlay.putalpha(overlay.getchannel('A').point(lambda a:round(a*alpha)))
    im.paste(overlay,(0,0),overlay)


def paper(im,cx,cy,width,text,alpha=1):
    if alpha<=0:return
    h=round(width*(.36 if '\n' in text else .20))
    card=Image.new('RGBA',(width,h));d=ImageDraw.Draw(card)
    d.rounded_rectangle((0,0,width-1,h-1),radius=18,fill='#F5F1E4')
    txt(card,round(width*.065),round(h*(.19 if '\n' in text else .29)),text,round(width*.052),'serif',INK)
    if alpha<1:card.putalpha(card.getchannel('A').point(lambda a:round(a*alpha)))
    im.paste(card,(round(cx-width/2),round(cy-h/2)),card)


def transfer(im,points,t,start,length=1.5):
    if t<start:return
    d=ImageDraw.Draw(im);u=beat(t,start,length)
    # A single path draws toward its destination. Its marker disappears on
    # arrival, leaving a quiet completed connection rather than an idle loop.
    samples=[]
    for q in np.linspace(0,u,70):
        x=(1-q)**2*points[0][0]+2*(1-q)*q*points[1][0]+q*q*points[2][0]
        y=(1-q)**2*points[0][1]+2*(1-q)*q*points[1][1]+q*q*points[2][1]
        samples.append((x,y))
    if len(samples)>1:d.line(samples,fill='#56897A',width=3)
    if u<1:
        x,y=samples[-1];d.rounded_rectangle((x-10,y-15,x+10,y+15),radius=3,fill=MINT)
    else:
        x,y=points[-1];d.ellipse((x-4,y-4,x+4,y+4),fill=MINT)


def scene(i,e,duration):
    im=(LIGHT if i==5 else DARK).copy()
    if i==0:
        txt(im,91,294,'Kindle +',105,'serif')
        txt(im,91,428,'Xteink',118,'serif',MINT)
        sub(im,98,609,'Keep your place between them.',31)
        u=beat(e,0,1.8)
        product(im,'kindle',mix(1430,1250,u),500,935,mix(0,45,u))
        product(im,'xteink',mix(1960,1620,u),641,596,mix(75,120,u))
    elif i==1:
        txt(im,960,129,'Keep your place',65,'serif',anchor='ma')
        u=beat(e,.2,1.1);v=beat(e,1.1,1.1)
        product(im,'kindle',mix(280,340,u),590,785,mix(45,80,u))
        product(im,'xteink',mix(1635,1575,v),638,500,mix(120,90,v))
        reveal_text(im,960,233,'Collect the highlights from both.',e,2,31,anchor='ma')
        q=beat(e,2.5,1.4)
        paper(im,mix(1550,965,q),mix(605,568,q)-90*math.sin(q*math.pi),round(mix(240,560,q)),
              'It is a truth universally\nacknowledged…',alpha=beat(e,2.5,.4))
    elif i==2:
        u=beat(e,0,.65)
        g.logo(im,820,round(mix(220,195,u)),280)
        txt(im,960,559,'Passage',112,'serif',anchor='ma')
        reveal_text(im,960,726,'A free, open-source Mac app.',e,.55,34,anchor='ma')
    elif i==3:
        im=app_frame('books',90,280,1730,(0,0,2360,974)).copy()
        txt(im,960,83,'Highlights from both readers',64,'serif',anchor='ma')
        sub(im,960,187,'From KOReader and CrossPoint',30,anchor='ma')
        # An editorial focus ring points at the actual book card; its position
        # and the native screenshot remain fixed throughout the shot.
        if 2<e<4.4:
            alpha=min(beat(e,2,.4),1-beat(e,3.6,.8))
            overlay=Image.new('RGBA',im.size)
            ImageDraw.Draw(overlay).rounded_rectangle((421,571,665,974),radius=24,outline=(*tuple(bytes.fromhex('AED8C6')),round(160*alpha)),width=3)
            im.paste(overlay,(0,0),overlay)
    elif i==4:
        im=app_frame('quotes',435,100,1310,None).copy()
        txt(im,82,265,'Find a\nhighlight.',54,'serif')
        sub(im,85,445,'Copy the quote,\nwith or without\nbook details.',27)
        q=beat(e,1.4,1.1)
        paper(im,mix(1370,244,q),mix(605,746,q),round(mix(470,330,q)),
              'It is a truth universally\nacknowledged…',alpha=min(beat(e,1.4,.2),1))
    elif i==5:
        u=beat(e,.15,1.1)
        product(im,'kindle',361,579,800,mix(45,80,u))
        txt(im,777,197,'Bring your',83,'serif',INK)
        txt(im,777,301,'Kindle highlights',83,'serif',INK)
        sub(im,784,436,'You can use Passage with one reader, too.',29,False)
        q=beat(e,3.4,1.35)
        paper(im,mix(387,1190,q),mix(560,652,q)-90*math.sin(q*math.pi),round(mix(260,800,q)),
              'My Clippings.txt',alpha=beat(e,3.4,.3))
        if e>4.75:g.logo(im,1650,582,128)
    elif i==6:
        txt(im,960,112,'Pick up where you left off',69,'serif',anchor='ma')
        sub(im,960,215,'Same EPUB, with manual controls on CrossPoint.',30,anchor='ma')
        u=beat(e,.2,1)
        product(im,'kindle',mix(330,376,u),624,725,mix(45,80,u))
        product(im,'xteink',mix(1595,1549,u),635,462,mix(120,90,u))
        g.logo(im,854,400,214)
        transfer(im,[(639,537),(739,466),(845,507)],e,2.8,1.05)
        transfer(im,[(1075,507),(1180,466),(1330,537)],e,4,1.25)
        reveal_text(im,790,735,'Upload Local',e,2.8,33,anchor='ma')
        reveal_text(im,1150,735,'Apply Remote',e,4,33,anchor='ma')
    elif i==7:
        im=app_frame('books',83,342,1190,(0,0,2360,974)).copy()
        txt(im,101,131,'Your library stays on your Mac',75,'serif')
        sub(im,105,244,'Back up to iCloud Drive or a folder you choose.',31)
        d=ImageDraw.Draw(im)
        # An ordinary folder illustration represents a completed backup.
        d.rounded_rectangle((1425,399,1531,443),radius=10,fill='#8CAEA1')
        d.rounded_rectangle((1425,425,1687,585),radius=17,fill='#B9D5C6')
        transfer(im,[(1230,570),(1340,635),(1475,514)],e,2.6,1.5)
        reveal_text(im,1555,632,'Backup saved',e,4.1,31,anchor='ma')
    elif i==8:
        txt(im,960,99,'Connect your readers',67,'serif',anchor='ma')
        u=beat(e,.3,1);v=beat(e,3,1)
        product(im,'kindle',470,521,640,mix(45,80,u))
        product(im,'xteink',1445,558,408,mix(120,90,v))
        reveal_text(im,470,858,'Jailbreak + KOReader',e,.3,31,anchor='ma')
        reveal_text(im,1445,858,'Matching Passage firmware',e,3,31,anchor='ma')
        reveal_text(im,960,965,'Your Mac must be awake and reachable.',e,5.5,27,anchor='ma')
    elif i==9:
        txt(im,92,270,'Free and',110,'serif')
        txt(im,92,412,'open source',110,'serif',MINT)
        sub(im,101,606,'Download the beta. The code is on GitHub.',32)
        u=beat(e,0,.85)
        g.logo(im,1270,round(mix(330,280,u)),370)
    else:
        u=beat(e,0,1.25)
        product(im,'kindle',mix(295,371,u),581,843,mix(80,45,u))
        product(im,'xteink',mix(835,685,u),665,537,mix(90,120,u))
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
    # Cues describe the on-screen action, not every cut: paper moves, a copy
    # lands, a reading position reaches the second reader, a backup completes.
    def sweep(start,length=.42,level=.012,pan=0):
        t=np.arange(int(length*sr))/sr
        high=np.r_[0,np.diff(rng.normal(0,1,len(t)))]
        add(start,high*np.sin(np.pi*t/length)**3*level,pan)
    def click(start,pan=0):
        t=np.arange(int(.1*sr))/sr
        add(start,(np.sin(2*np.pi*720*t)*.018+rng.normal(0,1,len(t))*.009)*np.exp(-t*54),pan)
    def chime(start,pan=0):
        for j,f in enumerate([523.25,659.25]):
            t=np.arange(int(.7*sr))/sr
            add(start+j*.12,np.sin(2*np.pi*f*t)*np.exp(-t*6)*np.minimum(1,t/.008)*.021,pan)
    sweep(INTRO,.7,.013,.35)
    sweep(STARTS[1]+INTRO+2.5,.6,.014,.5)
    chime(STARTS[2]+INTRO+.55)
    click(STARTS[4]+INTRO+1.4,.55)
    sweep(STARTS[4]+INTRO+1.5,.3,.007,-.3)
    click(STARTS[4]+INTRO+2.5,-.5)
    sweep(STARTS[5]+INTRO+3.4,.65,.013,-.4)
    click(STARTS[5]+INTRO+4.75,.55)
    click(STARTS[6]+INTRO+2.8,-.5)
    sweep(STARTS[6]+INTRO+4,.55,.008,.4)
    chime(STARTS[6]+INTRO+5.25,.5)
    chime(STARTS[7]+INTRO+4.1,.5)
    sweep(STARTS[10]+INTRO,.6,.008,-.2)
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
    frames=[scene(i,max(0,cuts[i+1]-s-.1),cuts[i+1]-s) for i,s in enumerate(STARTS)]
    for i,f in enumerate(frames):f.save(a.output/f'scene-{i:02}.jpg',quality=94)
    sheet=Image.new('RGB',(1920,1440))
    for i,f in enumerate(frames):sheet.paste(f.resize((640,360)),((i%3)*640,(i//3)*360))
    sheet.save(a.output/'contact-sheet.jpg',quality=93)
    thumb=DARK.copy()
    g.logo(thumb,102,103,151)
    txt(thumb,90,334,'Xteink + Kindle',89,'serif')
    txt(thumb,90,480,'Sync with Passage',71,'serif',MINT)
    product(thumb,'kindle',1260,494,990)
    product(thumb,'xteink',1654,658,631,120)
    thumb.resize((1280,720),Image.Resampling.LANCZOS).save(a.output/'Passage-thumbnail.jpg',quality=96)
    if a.preview:return
    cmd=['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1920x1080','-r',str(FPS),'-i','-','-an','-c:v','libx264','-preset','fast','-crf','17','-pix_fmt','yuv420p','-movflags','+faststart',str(a.output/'picture.mp4')]
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    for frame in range(math.ceil(duration*FPS)):
        t=frame/FPS;local=max(0,t-INTRO);i=max(0,min(10,bisect.bisect_right(STARTS,local)-1));e=local-STARTS[i]
        im=scene(i,e,cuts[i+1]-STARTS[i])
        if i and e<.20:im=Image.blend(frames[i-1],im,e/.20)
        proc.stdin.write(im.tobytes())
        if frame%(FPS*10)==0:print(f'Rendered {t:.0f}/{duration:.1f}s',flush=True)
    proc.stdin.close()
    if proc.wait():raise SystemExit('Video encoding failed')
    soundtrack(a.output/'music-and-sfx.wav',duration)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(a.output/'picture.mp4'),'-i',str(a.output/'narration-master.wav'),'-i',str(a.output/'music-and-sfx.wav'),
        '-filter_complex','[1:a]loudnorm=I=-16:TP=-2:LRA=8,aformat=channel_layouts=stereo,adelay=750|750,apad[v];[2:a]volume=0.8[m];[v][m]amix=inputs=2:normalize=0:duration=longest,alimiter=limit=0.87[a]',
        '-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-b:a','256k','-ar','48000','-t',str(duration),'-movflags','+faststart',str(a.output/'Passage-release-film.mp4')],check=True)
    (a.output/'render.json').write_text(json.dumps({'duration':duration,'width':W,'height':H,'fps':FPS,'devices':'Blender models of Kindle Paperwhite 11th generation and Xteink X4 Pro; original typeset public-domain pages','screenshots':'Native Passage app; sample library','music_and_sfx':'Original score with action-linked paper, copy, progress and backup cues','narration':'Gemini 3.8 Flash TTS / Charon / v1beta Interactions; original speech speed','captioned':False,'supporting_text':'Selective lines below headings; no eyebrows above headings','motion':'Finite directed device moves and one-shot transfer illustrations; native app screenshots stay fixed'},indent=2)+'\n')
    print('Finished',a.output/'Passage-release-film.mp4',flush=True)

if __name__=='__main__':main()
