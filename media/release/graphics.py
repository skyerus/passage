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
STARTS = [0, 2.8, 9.0, 13.0, 23.0, 28.0, 33.8, 42.8, 50.8, 60.6, 65.6]
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


