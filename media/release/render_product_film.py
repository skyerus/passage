"""Passage film: Blender device models, native UI, kinetic typography and original SFX."""
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

def label(im,x,y,value,dark=True):g.pill(im,x,y,value,dark,22)

@lru_cache(maxsize=24)
def plate(name,index):return Image.open(PLATES/name/f'{index:04}.png').convert('RGBA')

def product(im,name,cx,cy,height,t,phase=0,angle=0):
    index=int(((t/6+phase)%1)*179)
    if not (PLATES/name/f'{index:04}.png').exists():index=0
    p=plate(name,index).resize((int(height*.76),int(height)),Image.Resampling.LANCZOS)
    if angle:p=p.rotate(angle,Image.Resampling.BICUBIC,expand=True)
    im.paste(p,(int(cx-p.width/2),int(cy-p.height/2)),p)

def shot(im,name,x,y,width,t=0,crop=None):
    g.screenshot(im,name,int(x+8*math.sin(t*.45)),int(y+6*math.cos(t*.3)),int(width),crop)

def quote_card(im,x,y,scale=1):
    layer=Image.new('RGBA',(int(568*scale),int(218*scale)));d=ImageDraw.Draw(layer)
    d.rounded_rectangle((0,0,layer.width-1,layer.height-1),radius=24*scale,fill='#F5F1E4')
    g.text(layer,(28*scale,18*scale),'“',int(76*scale),'serif',TEAL)
    g.text(layer,(91*scale,46*scale),'It is a truth universally\nacknowledged…',int(29*scale),'serif',INK,spacing=12*scale)
    g.text(layer,(94*scale,151*scale),'PRIDE AND PREJUDICE',int(17*scale),'bold',TEAL)
    im.paste(layer,(int(x),int(y)),layer)

def trail(im,x1,y1,x2,y2,t):
    d=ImageDraw.Draw(im);pts=[(x1+(x2-x1)*u,y1+(y2-y1)*u-80*math.sin(u*math.pi)) for u in np.linspace(0,1,90)]
    d.line(pts,fill='#39685A',width=3);u=t%1;x=x1+(x2-x1)*u;y=y1+(y2-y1)*u-80*math.sin(u*math.pi)
    d.ellipse((x-10,y-10,x+10,y+10),fill=MINT)

def scene(i,e,duration):
    dark=i not in (4,5,7);im=(DARK if dark else LIGHT).copy();enter=ease(e/.85);dy=int((1-enter)*65);t=e+STARTS[i]
    txt(im,78,48,'PASSAGE',23,'bold',MINT if dark else TEAL)
    txt(im,1840,48,'READING, TOGETHER.',20,color=MINT if dark else TEAL,anchor='ra')
    if i==0:
        label(im,98,212,'KINDLE + XTEINK');txt(im,91,319+dy,'New reader.',100,'serif');txt(im,91,446+dy,'Same you.',110,'serif',MINT)
        txt(im,98,642,'Why start your reading life over?',33,color='#A6BAAF')
        product(im,'kindle',1250+230*(1-enter),500,935,t,0);product(im,'xteink',1620+480*(1-enter),641,596,t,.42)
        txt(im,1220,940,'PAPERWHITE',19,'bold',MINT,anchor='ma');txt(im,1640,940,'X4 PRO',19,'bold',MINT,anchor='ma')
    elif i==1:
        txt(im,960,150+dy,'Good books. Scattered highlights.',65,'serif',anchor='ma')
        product(im,'kindle',330,602,763,t,.05);product(im,'xteink',1590,647,486,t,.54)
        quote_card(im,620-200*(1-ease((e-.4)/1)),397+math.sin(e)*9)
        txt(im,960,668,'On the other reader.',38,'serif',MINT,anchor='ma');trail(im,520,720,1400,720,e/3)
    elif i==2:
        size=int(230+50*enter);g.logo(im,960-size/2,175+dy,size)
        txt(im,960,505+dy,'Meet Passage.',112,'serif',anchor='ma');txt(im,960,664,'Your reading, together.',41,color=MINT,anchor='ma')
        label(im,753,786,'FREE + OPEN SOURCE');product(im,'kindle',192-40*enter,638,523,t,0,13);product(im,'xteink',1723+30*enter,636,333,t,.55,-13)
    elif i==3:
        txt(im,90,162+dy,'Every passage.',65,'serif');txt(im,90,242+dy,'One library.',65,'serif',MINT)
        product(im,'kindle',216,570,516,t,.12,-3);product(im,'xteink',448,644,329,t,.64,3)
        shot(im,'books',670+90*(1-enter),180,1150+int(8*math.sin(e*.45)),t)
        for j,(x,value) in enumerate([(92,'COVERS'),(258,'DATES'),(406,'SEARCH')]):
            if e>j*.8:label(im,x,867,value)
        txt(im,680,971,'Actual Passage app · sample library',17,color=MINT)
        if 2<e<4.1:
            u=ease((e-2)/2.1);quote_card(im,310+470*u,690-300*math.sin(u*math.pi),.43)
    elif i==4:
        txt(im,90,197+dy,'Find it.',76,'serif',INK);txt(im,90,291+dy,'Keep it.',76,'serif',INK);txt(im,90,385+dy,'Share it.',76,'serif',TEAL)
        shot(im,'quotes',740,155,1060,t,crop=(510,130,1174,618));label(im,96,648,'COPY QUOTE',False)
        if e>.75:label(im,96,727,'WITH BOOK + AUTHOR',False)
    elif i==5:
        product(im,'kindle',361,579,800,t,.13);txt(im,777,178+dy,'Bring years',83,'serif',INK);txt(im,777,282+dy,'of highlights.',83,'serif',INK)
        ImageDraw.Draw(im).rounded_rectangle((778,442,1780,678),radius=22,fill='#FFFDF4')
        txt(im,832,478,'My Clippings.txt',52,'serif',INK);txt(im,835,571,'Import the archive you already have.',29,color=TEAL)
        txt(im,791,770,'One reader is enough.',42,'serif',TEAL);txt(im,795,839,'No jailbreak needed to import.',25,color='#59695B')
        ImageDraw.Draw(im).line((814,712,814+int(890*ease(e/1.3)),712),fill=TEAL,width=5)
    elif i==6:
        txt(im,960,140+dy,'Continue at the same passage.',69,'serif',anchor='ma')
        product(im,'kindle',376,611,749,t,.17);product(im,'xteink',1549,622,477,t,.61);g.logo(im,854,414+12*math.sin(e),214)
        trail(im,675,518,827,518,e*.6);trail(im,1110,518,1322,518,e*.6+.3)
        txt(im,960,686,'SAME EPUB',26,'bold',MINT,anchor='ma');txt(im,960,781,'Upload Local / Apply Remote',35,'serif',anchor='ma')
        txt(im,960,842,'CrossPoint progress controls',25,color=MINT,anchor='ma');txt(im,960,930,'Illustrated progress flow',18,color='#A4BCAF',anchor='ma')
    elif i==7:
        txt(im,101,143+dy,'Your library. Your Mac.',87,'serif',INK);shot(im,'books',104,310,980,t)
        for j,(y,title,sub) in enumerate([(375,'iCloud Drive','Or any folder you choose.'),(580,'No hosting bill.','Your Mac hosts Passage.'),(785,'No GitHub account.','Download it and get started.')]):
            dx=65*(1-ease((e-.2-j*.3)/.75));txt(im,1260+dx,y,title,40,'serif',INK);txt(im,1262+dx,y+66,sub,24,color=TEAL)
    elif i==8:
        txt(im,960,138+dy,'A little setup. Then keep reading.',67,'serif',anchor='ma')
        product(im,'kindle',470,521,611,t,.16);product(im,'xteink',1445,553,390,t,.66)
        txt(im,470,801,'Supported jailbreak + KOReader',30,'serif',anchor='ma');txt(im,1445,801,'Matching Passage firmware',30,'serif',anchor='ma')
        txt(im,960,900,'Your Mac must be awake and reachable for uploads.',27,color=MINT,anchor='ma')
    elif i==9:
        label(im,99,189,'PUBLIC BETA FOR MAC');txt(im,92,300+dy,'Free.',118,'serif');txt(im,92,442+dy,'Open source.',118,'serif',MINT)
        txt(im,103,660,'Download it. Explore it. Make it yours.',36,color='#BED1C4');g.logo(im,1270,240+dy,370)
        txt(im,1460,707,'MIT-LICENSED APP',24,'bold',MINT,anchor='ma');txt(im,105,848,'github.com/skyerus/passage',39,'bold')
    else:
        product(im,'kindle',371,581,843,t,.18,-3);product(im,'xteink',685,665,537,t,.65,4);g.logo(im,1050,213,135)
        txt(im,1038,402+dy,'Keep the words.',75,'serif');txt(im,1038,496+dy,'Choose the reader.',75,'serif',MINT)
        txt(im,1043,692,'github.com/skyerus/passage',36,'bold');txt(im,1044,758,'Apple Silicon Mac · Public beta',27,color='#B4CDC0');txt(im,1044,816,'Link in the description',25,color='#B4CDC0')
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
    for start in [s+INTRO for s in STARTS[1:]]:
        t=np.arange(int(.43*sr))/sr;high=np.r_[0,np.diff(rng.normal(0,1,len(t)))];env=np.sin(np.pi*t/.43)**3
        add(max(0,start-.20),high*env*.019,.65)
    for start in [7.5,20.8,22.3,24.2,30.5,31.9,36.5,43.2,48.2]:
        t=np.arange(int(.105*sr))/sr;sound=(rng.normal(0,1,len(t))*.017+np.sin(2*np.pi*620*t)*.011)*np.exp(-t*58);add(start,sound,-.5)
    for start in [13.7,71.7,77.3]:
        for j,f in enumerate([523.25,659.25,783.99]):
            t=np.arange(int(.85*sr))/sr;add(start+j*.105,np.sin(2*np.pi*f*t)*np.exp(-t*6)*np.minimum(1,t/.008)*.023,j/2-.5)
    a*=(np.minimum(1,np.arange(n)/sr/1.5)*np.minimum(1,(duration-np.arange(n)/sr)/2.3))[:,None]
    with wave.open(str(path),'wb') as out:
        out.setnchannels(2);out.setsampwidth(2);out.setframerate(sr);out.writeframes(np.int16(np.clip(a,-1,1)*32767).tobytes())

def main():
    global PLATES
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--plates',type=Path,required=True);p.add_argument('--preview',action='store_true')
    a=p.parse_args();PLATES=a.plates;a.output.mkdir(parents=True,exist_ok=True)
    with wave.open(str(a.output/'narration-paced.wav')) as w:duration=w.getnframes()/w.getframerate()+INTRO+2.5
    cuts=STARTS+[duration-INTRO];caps=g.captions(a.output/'narration.json')
    (a.output/'Passage-captions.srt').write_text('\n\n'.join(f'{j+1}\n{g.stamp(c["start"])} --> {g.stamp(c["end"])}\n{c["text"]}' for j,c in enumerate(caps))+'\n')
    frames=[scene(i,2,cuts[i+1]-s) for i,s in enumerate(STARTS)]
    for i,f in enumerate(frames):f.save(a.output/f'scene-{i:02}.jpg',quality=94)
    sheet=Image.new('RGB',(1920,1440))
    for i,f in enumerate(frames):sheet.paste(f.resize((640,360)),((i%3)*640,(i//3)*360))
    sheet.save(a.output/'contact-sheet.jpg',quality=93)
    thumb=DARK.copy();g.logo(thumb,102,103,151);txt(thumb,90,334,'Your highlights.',99,'serif');txt(thumb,90,463,'Together.',118,'serif',MINT)
    txt(thumb,98,682,'KINDLE + XTEINK',33,'bold',MINT);label(thumb,99,786,'FREE + OPEN SOURCE')
    product(thumb,'kindle',1260,494,990,1.1,.02);product(thumb,'xteink',1654,658,631,1.1,.55)
    thumb.resize((1280,720),Image.Resampling.LANCZOS).save(a.output/'Passage-thumbnail.jpg',quality=96)
    if a.preview:return
    cmd=['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1920x1080','-r',str(FPS),'-i','-','-an','-c:v','libx264','-preset','fast','-crf','17','-pix_fmt','yuv420p','-movflags','+faststart',str(a.output/'picture.mp4')]
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    for frame in range(math.ceil(duration*FPS)):
        t=frame/FPS;local=max(0,t-INTRO);i=max(0,min(10,bisect.bisect_right(STARTS,local)-1));e=local-STARTS[i]
        im=scene(i,e,cuts[i+1]-STARTS[i])
        if i and e<.20:im=Image.blend(scene(i-1,cuts[i]-STARTS[i-1],cuts[i]-STARTS[i-1]),im,e/.20)
        c=next((c for c in caps if c['start']<=t<c['end']),None)
        if c:
            d=ImageDraw.Draw(im);f=g.font(29);width=d.textlength(c['text'],font=f)+48
            d.rounded_rectangle(((W-width)/2,996,(W+width)/2,1054),radius=14,fill='#0E2E26');d.text((W/2,1008),c['text'],font=f,fill=CREAM,anchor='ma')
        proc.stdin.write(im.tobytes())
        if frame%(FPS*10)==0:print(f'Rendered {t:.0f}/{duration:.1f}s',flush=True)
    proc.stdin.close()
    if proc.wait():raise SystemExit('Video encoding failed')
    soundtrack(a.output/'music-and-sfx.wav',duration)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(a.output/'picture.mp4'),'-i',str(a.output/'narration-master.wav'),'-i',str(a.output/'music-and-sfx.wav'),
        '-filter_complex','[1:a]loudnorm=I=-16:TP=-2:LRA=8,aformat=channel_layouts=stereo,adelay=750|750,apad[v];[2:a]volume=0.8[m];[v][m]amix=inputs=2:normalize=0:duration=longest,alimiter=limit=0.87[a]',
        '-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-b:a','256k','-ar','48000','-t',str(duration),'-movflags','+faststart',str(a.output/'Passage-release-film.mp4')],check=True)
    (a.output/'render.json').write_text(json.dumps({'duration':duration,'width':W,'height':H,'fps':FPS,'devices':'Blender models of Kindle Paperwhite 11th generation and Xteink X4 Pro; original typeset public-domain pages','screenshots':'Native Passage app; sample library','music_and_sfx':'Original synthesized score, swishes, page flicks, clicks and chimes','narration':'Gemini TTS','captioned':True},indent=2)+'\n')
    print('Finished',a.output/'Passage-release-film.mp4',flush=True)

if __name__=='__main__':main()
