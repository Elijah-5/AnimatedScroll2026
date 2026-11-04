from pathlib import Path
from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
# Dedicated database configuration; model credentials remain in the existing .env.
load_dotenv(ROOT / '.env.mysql')


import os
# Allow slow first-time model downloads without changing TLS verification.
os.environ.setdefault('HF_HUB_DOWNLOAD_TIMEOUT','120')
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelSettings:
    provider: str
    api_key: str = field(repr=False)
    base_url: str
    model: str


def model_settings(kind='text', require_key=True, purpose=''):
    provider=os.getenv('MODEL_PROVIDER', 'aihubmix')
    if provider=='dashscope':
        key_name='DASHSCOPE_API_KEY'
        base_url=os.getenv('DASHSCOPE_BASE_URL','https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1')
        model=os.getenv('DASHSCOPE_VISION_MODEL' if kind=='vision' else 'DASHSCOPE_MODEL')
        model=model or os.getenv('DASHSCOPE_MODEL','deepseek-v4.1-flash')
    elif provider=='aihubmix':
        key_name='AIHUBMIX_API_KEY'
        base_url=os.getenv('AIHUBMIX_BASE_URL','https://aihubmix.com/v1')
        model=os.getenv('AIHUBMIX_VISION_MODEL','gpt-4o') if kind=='vision' else os.getenv('AIHUBMIX_MODEL','deepseek-v4.1-flash-1017')
    else:
        raise ValueError('MODEL_PROVIDER 仅支持 dashscope 或 aihubmix')
    if kind=='text' and purpose in ('defaults','dialogue'):
        prefix='DASHSCOPE' if provider=='dashscope' else 'AIHUBMIX'
        model=os.getenv(prefix+'_'+purpose.upper()+'_MODEL') or model
    api_key=os.getenv(key_name,'')
    if require_key and not api_key:raise ValueError('未配置 '+key_name+'，请设置后重启后端')
    return ModelSettings(provider=provider,api_key=api_key,base_url=base_url,model=model)
