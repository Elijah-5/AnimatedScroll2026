"""Provider contract. AIHubMix/Wan implementation is intentionally not enabled."""
from typing import Protocol


class VideoAdapter(Protocol):
    def profile(self) -> dict: ...
    def validate_configuration(self) -> None: ...
    def build_request(self,job:dict,image_path) -> dict: ...
    async def submit(self,job:dict,body:dict) -> str: ...
    async def inspect(self,job:dict) -> dict: ...
    async def download(self,job:dict,result:dict) -> bytes: ...


# An integration registers an adapter here after verifying its model, price,
# references and credentials. Reading a page never initializes a remote model.
ADAPTERS:dict[str,VideoAdapter]={}
PROVIDER='aihubmix'


def active():return ADAPTERS.get(PROVIDER)


def profile():
    adapter=active()
    if not adapter:
        return dict(provider=PROVIDER,model=None,resolution='1080P',duration=5,audio=False,
                    estimatedCny=None,ready=False,message='视频模型待接入，当前不会提交任务或扣额度')
    return dict(adapter.profile(),provider=PROVIDER,ready=True)


def request_config():
    info=profile()
    return dict(provider=info['provider'],model=info['model'],mediaMode='reference_images',
                parameters=dict(resolution=info['resolution'],duration=info['duration'],audio=info.get('audio',False),ratio='adaptive',prompt_extend=False))
