"""Derived, local-only person mattes. No creation data or remote models are written."""
import hashlib
import io
import json
import math
import os
import threading
import uuid
from pathlib import Path
from PIL import Image, ImageOps, ImageFilter, ImageDraw
from . import config

MODEL = config.ROOT / 'models' / 'slimsam-77-uniform'
POLICY = 'slimsam-72a5ae6-instance-head-v4'
_model = None
_lock = threading.Lock()


def valid_box(box):
    return (isinstance(box, dict) and all(isinstance(box.get(k), (int, float)) and not isinstance(box[k], bool)
            and math.isfinite(box[k]) for k in ('x', 'y', 'w', 'h'))
            and min(box['x'], box['y']) >= 0 and min(box['w'], box['h']) > 0
            and box['x'] + box['w'] <= 1.000001 and box['y'] + box['h'] <= 1.000001)


def portrait_box(character, annotation):
    for box in (character.get('faceRegion'), annotation.get('faceRegion')):
        if valid_box(box):
            return {k: box[k] for k in ('x', 'y', 'w', 'h')}
    return dict(x=annotation['x'], y=annotation['y'], w=annotation['w'], h=annotation['h'] / 3)


def source(p, data):
    from .consumption import confirmed
    url = confirmed(p, 'material', 'main').get('image', '')
    if not url.startswith('/api/images/') or Path(url).name != url.removeprefix('/api/images/'):
        raise ValueError('已确认原画的路径无效')
    path = Path(data) / Path(url).name
    if not path.is_file():
        raise ValueError('已确认的原画文件不存在')
    return path


def instance_head(person):
    body=person['box'];face=person.get('portraitBox')
    # A shared character avatar may be a different member of the same group.
    # It must never become a foreground seed clamped to this instance's edge.
    if valid_box(face) and body['x']<=face['x']+face['w']/2<=body['x']+body['w'] and body['y']<=face['y']+face['h']/2<=body['y']+body['h']:
        return face
    return dict(body,h=body['h']/3)


def point_prompts(person, people):
    box=instance_head(person)
    points=[(box['x']+box['w']/2,box['y']+box['h']/2)]
    labels=[1]
    b=person['box']
    for other in people:
        if other['annotationId']==person['annotationId']:continue
        head=instance_head(other)
        x,y=head['x']+head['w']/2,head['y']+head['h']/2
        if b['x']-b['w']*.18<=x<=b['x']+b['w']*1.18 and b['y']-b['h']*.12<=y<=b['y']+b['h']*1.12:
            # Nearby heads disambiguate overlapping figures rather than fusing them.
            if math.hypot(x-points[0][0],y-points[0][1])>.01:
                points.append((x,y));labels.append(0)
    return points,labels


def key_for(image_hash, person, people=()):
    payload = json.dumps([POLICY, image_hash, person['box'],point_prompts(person,people)], sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def segment(image, box, prompts=None):
    """Box-prompted SAM on a padded local crop retains small painted figures."""
    global _model
    if not (MODEL / 'model.safetensors').is_file():
        raise ValueError('本地抠图模型未准备，请运行 .venv/bin/python scripts/prepare_cutouts.py')
    import torch
    from transformers import SamModel, SamProcessor
    if _model is None:
        _model = (SamProcessor.from_pretrained(MODEL, local_files_only=True),
                  SamModel.from_pretrained(MODEL, local_files_only=True).eval())
    processor, model = _model
    w, h = image.size
    x, y, r, b = box['x'] * w, box['y'] * h, (box['x'] + box['w']) * w, (box['y'] + box['h']) * h
    region = (max(0, int(x - (r-x)*.18)), max(0, int(y - (b-y)*.12)),
              min(w, math.ceil(r + (r-x)*.18)), min(h, math.ceil(b + (b-y)*.12)))
    crop = image.crop(region)
    options={}
    if prompts:
        points,labels=prompts
        options=dict(input_points=[[[min(crop.width-1,max(0,px*w-region[0])),min(crop.height-1,max(0,py*h-region[1]))] for px,py in points]],input_labels=[labels])
    inputs = processor(images=crop, input_boxes=[[[x-region[0], y-region[1], r-region[0], b-region[1]]]], return_tensors='pt',**options)
    with torch.inference_mode():
        out = model(**inputs, multimask_output=True)
    masks = processor.image_processor.post_process_masks(out.pred_masks, inputs['original_sizes'], inputs['reshaped_input_sizes'])[0][0]
    # The model's quality score chooses among its alternative object masks.
    best = int(out.iou_scores[0, 0].argmax())
    alpha = Image.fromarray(masks[best].numpy().astype('uint8') * 255, 'L')
    crop.putalpha(alpha)
    local = (round(x)-region[0], round(y)-region[1], round(r)-region[0], round(b)-region[1])
    result = crop.crop(local)
    result.putalpha(clean_mask(result.getchannel('A')))
    coverage = sum(result.getchannel('A').histogram()[1:]) / max(1, result.width * result.height)
    if not .015 < coverage < .985:
        raise ValueError('未能分离可靠的人物轮廓；请检查此人物框选范围')
    result.thumbnail((1200, 1800))
    return result


def clean_mask(mask):
    """Remove pixel speckle and internal pinholes that would glow inside clothing."""
    padded=ImageOps.expand(mask,border=3,fill=0)
    padded=padded.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))
    padded=padded.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    outside=padded.copy()
    ImageDraw.floodfill(outside,(0,0),128)
    # Exterior remains transparent. Filled interior holes avoid broken clothing.
    alpha=outside.point(lambda value:0 if value==128 else 255)
    return alpha.crop((3,3,alpha.width-3,alpha.height-3))


def prepare(p, people, data, progress=None):
    path = source(p, data)
    image_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    root = Path(data) / 'experience-cutouts'
    root.mkdir(exist_ok=True)
    rows = []
    # One local inference at a time, and a second cache check prevents duplicates.
    with _lock:
        image = None
        for index, person in enumerate(people):
            row = dict(annotationId=person['annotationId'])
            if not valid_box(person['box']):
                rows.append(dict(row, error='人物框范围无效'))
                if progress:progress(rows[-1],index+1,len(people))
                continue
            key = key_for(image_hash, person, people)
            target = root / (key + '.png')
            try:
                if not target.is_file():
                    if image is None:
                        image = ImageOps.exif_transpose(Image.open(path)).convert('RGB')
                    rgba = segment(image, person['box'],point_prompts(person,people))
                    buf = io.BytesIO(); rgba.save(buf, format='PNG')
                    tmp = root / (key + '-' + uuid.uuid4().hex + '.tmp')
                    tmp.write_bytes(buf.getvalue()); os.replace(tmp, target)
                rows.append(dict(row, key=key))
            except (ValueError, OSError, RuntimeError) as exc:
                rows.append(dict(row, error=str(exc)[:180]))
            if progress:progress(rows[-1],index+1,len(people))
    return rows
