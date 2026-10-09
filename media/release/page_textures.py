"""Typeset crisp public-domain EPUB page textures for the product renders."""
from pathlib import Path
import argparse
import textwrap
from PIL import Image, ImageDraw, ImageFont


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output
    output.mkdir(parents=True, exist_ok=True)
    fonts = Path('/System/Library/Fonts/Supplemental')
    for name, width, height, size in [('kindle', 1236, 1648, 45), ('xteink', 900, 1492, 39)]:
        page = Image.new('RGB', (width, height), '#EEEBDC')
        d = ImageDraw.Draw(page)
        body = ImageFont.truetype(str(fonts/'Georgia.ttf'), size)
        title = ImageFont.truetype(str(fonts/'Georgia.ttf'), size + 10)
        ui = ImageFont.truetype(str(fonts/'Arial.ttf'), 23)
        d.text((width/2, 61), 'PRIDE AND PREJUDICE', font=ui, fill='#4B4A43', anchor='mt')
        d.text((width/2, 165), 'Chapter I', font=title, fill='#292A26', anchor='mt')
        paragraphs = [
            'It is a truth universally acknowledged, that a single man in possession of a good fortune, must be in want of a wife.',
            'However little known the feelings or views of such a man may be on his first entering a neighbourhood, this truth is so well fixed in the minds of the surrounding families, that he is considered the rightful property of some one or other of their daughters.',
            '\u201cMy dear Mr. Bennet,\u201d said his lady to him one day, \u201chave you heard that Netherfield Park is let at last?\u201d',
            'Mr. Bennet replied that he had not.',
        ]
        y = 304
        for paragraph_index, paragraph in enumerate(paragraphs):
            words = paragraph.split(); lines = []; current = ''
            for word in words:
                candidate = (current+' '+word).strip()
                if d.textlength(candidate,font=body)>width-148:
                    lines.append(current);current=word
                else:current=candidate
            lines.append(current)
            for line in lines:
                if y > height-135:break
                if paragraph_index == 0:
                    d.rectangle((68,y-3,76+d.textlength(line,font=body),y+size+12),fill='#CACDB9')
                d.text((74,y),line,font=body,fill='#252923')
                y += size*1.48
            y += size*.65
        d.text((width/2,height-58),'1',font=ui,fill='#64685C',anchor='mt')
        page.save(output/f'{name}-page.png')


if __name__ == '__main__':
    main()
