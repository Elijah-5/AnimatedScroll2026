"""Project titles use the artwork name; duplicate projects keep stable suffixes."""
import re

def artwork_name(value):
    return re.split(r'\s*[·|]\s*',str(value or ''),maxsplit=1)[0].strip() or '未命名画作'

def unique_title(name,occupied,preferred=''):
    name=artwork_name(name)
    suffix=re.fullmatch(re.escape(name)+r'\(([0-9]+)\)',preferred)
    if preferred not in occupied and (preferred==name or (suffix and int(suffix[1])>=2)):
        return preferred
    if name not in occupied:return name
    number=2
    while f'{name}({number})' in occupied:number+=1
    return f'{name}({number})'
