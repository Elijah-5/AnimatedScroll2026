"""Explicitly download local SlimSAM weights; appreciation never downloads models."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from huggingface_hub import snapshot_download
from backend import config

MODEL_ID = 'nielsr/slimsam-77-uniform'
REVISION = '72a5ae6ca4d1da579a001f6f008b6fb949282c10'

def prepare():
    root = config.ROOT / 'models' / 'slimsam-77-uniform'
    snapshot_download(MODEL_ID, revision=REVISION, local_dir=root,
                      allow_patterns=['config.json', 'preprocessor_config.json', 'model.safetensors'])
    from transformers import SamModel, SamProcessor
    SamProcessor.from_pretrained(root, local_files_only=True)
    SamModel.from_pretrained(root, local_files_only=True).eval()
    print('SlimSAM local model ready: ' + str(root), flush=True)

if __name__ == '__main__':
    prepare()
