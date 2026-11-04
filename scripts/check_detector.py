"""Run local detector diagnostics without cloud model calls or database writes."""
import json
from pathlib import Path
from backend import config,vision

if __name__=='__main__':
    missing=vision.missing_detector_modules()
    if missing:
        print(json.dumps(dict(ok=False,missingModules=missing),ensure_ascii=True))
        raise SystemExit(1)
    image=config.ROOT/'examples'/'assets'/'latest-project.png'
    try:
        found=vision.detect(image,lambda progress:print(progress,flush=True))
        target=config.ROOT/'data'/'detector-check.json'
        target.write_text(json.dumps(dict(image=str(image),detections=found),ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(ok=True,peopleDetected=len(found),result=str(target)),ensure_ascii=True))
    except ModuleNotFoundError as exc:
        print(json.dumps(dict(ok=False,missingModule=exc.name),ensure_ascii=True));raise SystemExit(1)
