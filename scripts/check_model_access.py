import asyncio
import base64
import io
import json
from PIL import Image
from openai import AsyncOpenAI
from backend import config

async def check(kind):
    settings=config.model_settings(kind)
    client=AsyncOpenAI(api_key=settings.api_key,base_url=settings.base_url,timeout=45,max_retries=0)
    content='Reply OK.'
    if kind=='vision':
        stream=io.BytesIO();Image.new('RGB',(64,64),'white').save(stream,format='PNG')
        encoded=base64.b64encode(stream.getvalue()).decode()
        content=[dict(type='image_url',image_url=dict(url='data:image/png;base64,'+encoded)),dict(type='text',text='请用一个词回答这张图片的主要颜色。')]
    try:
        response=await client.chat.completions.create(model=settings.model,messages=[dict(role='user',content=content)],max_tokens=128)
        output=response.choices[0].message.content or ''
        return dict(kind=kind,provider=settings.provider,model=settings.model,ok=bool(output.strip()),output=output[:150])
    except Exception as exc:
        return dict(kind=kind,provider=settings.provider,model=settings.model,ok=False,error=type(exc).__name__,status=getattr(exc,'status_code',None))
    finally:await client.close()

async def main():
    for result in await asyncio.gather(check('text'),check('vision')):
        print(json.dumps(result,ensure_ascii=True))

if __name__=='__main__':asyncio.run(main())
