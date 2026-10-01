"""Read/write KOReader's literal Lua settings without executing any Lua code."""
import math
import re


def loads(text):
    if len(text.encode()) > 8 * 1024 * 1024: raise ValueError('Settings too large')
    pos = 0
    def whitespace():
        nonlocal pos
        while True:
            match = re.match(r'\s+|--\[(=*)\[', text[pos:])
            if match:
                pos += len(match[0])
                if match[0].startswith('--'):
                    end = text.find(']' + match[1] + ']', pos)
                    if end < 0: raise ValueError('Unterminated comment')
                    pos = end + len(match[1]) + 2
            elif text.startswith('--',pos):
                end = text.find('\n',pos); pos = len(text) if end < 0 else end+1
            else: return
    def token(value):
        nonlocal pos
        whitespace()
        if not text.startswith(value,pos): raise ValueError('Unsupported settings syntax')
        pos += len(value)
    def value(depth=0):
        nonlocal pos
        if depth > 60: raise ValueError('Settings too deep')
        whitespace()
        if pos >= len(text): raise ValueError('Truncated settings')
        c=text[pos]
        if c in ('"',"'"):
            quote=c;pos+=1;out=bytearray()
            escapes={'a':7,'b':8,'f':12,'n':10,'r':13,'t':9,'v':11,'\\':92,'"':34,"'":39}
            while pos<len(text) and text[pos]!=quote:
                c=text[pos];pos+=1
                if c=='\\':
                    if pos>=len(text): raise ValueError('Unterminated string')
                    c=text[pos];pos+=1
                    if c in escapes: out.append(escapes[c])
                    elif c.isdigit():
                        m=re.match(r'\d{0,2}',text[pos:]);digits=c+m[0];pos+=len(m[0]);out.append(int(digits))
                    elif c=='x': out.append(int(text[pos:pos+2],16));pos+=2
                    elif c=='\n': out.append(10)
                    else: raise ValueError('Unsupported string escape')
                else: out.extend(c.encode('utf-8'))
            if pos>=len(text): raise ValueError('Unterminated string')
            pos+=1;return out.decode('utf-8')
        if c=='{':
            pos+=1;result={};index=1
            while True:
                whitespace()
                if text.startswith('}',pos): pos+=1;return result
                if text.startswith('[',pos):
                    token('[');key=value(depth+1);token(']');token('=');item=value(depth+1)
                else:
                    m=re.match(r'([A-Za-z_]\w*)\s*=',text[pos:])
                    if m: key=m[1];pos+=len(m[0]);item=value(depth+1)
                    else: key=index;index+=1;item=value(depth+1)
                if type(key) not in (str,int,float) or key in result: raise ValueError('Invalid or duplicate settings key')
                result[key]=item
                whitespace()
                if text.startswith((',', ';'),pos): pos+=1
                elif not text.startswith('}',pos): raise ValueError('Missing table separator')
        for literal,result in [('true',True),('false',False),('nil',None)]:
            if text.startswith(literal,pos): pos+=len(literal);return result
        m=re.match(r'-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',text[pos:])
        if m:
            pos+=len(m[0]);result=float(m[0]) if any(c in m[0] for c in '.eE') else int(m[0])
            if not math.isfinite(result): raise ValueError('Invalid number')
            return result
        raise ValueError('Only literal settings are supported; no Lua code is executed')
    token('return');result=value();whitespace()
    if pos<len(text) and text[pos]==';': pos+=1;whitespace()
    if pos!=len(text) or not isinstance(result,dict): raise ValueError('Unexpected settings contents')
    return result


def dumps(value):
    def encode(v, depth=0):
        if isinstance(v,dict):
            return '{\n' + ''.join('    '*(depth+1)+'['+encode(k)+'] = '+encode(item,depth+1)+',\n' for k,item in v.items()) + '    '*depth+'}'
        if isinstance(v,str):
            return '"'+''.join('\\'+c if c in '\\"' else ('\\%03d'%ord(c)) if ord(c)<32 or ord(c)==127 else c for c in v)+'"'
        if v is None: return 'nil'
        if isinstance(v,bool): return 'true' if v else 'false'
        if isinstance(v,(int,float)) and math.isfinite(v): return str(v)
        raise ValueError('Unsupported settings value')
    return 'return '+encode(value)+'\n'
