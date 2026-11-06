"""Only for regression tests. All remote traffic is replaced by MockTransport."""
import httpx
from backend import video


class FakeVideoAdapter:
    def profile(self):
        return dict(model=video.VIDEO_MODEL,resolution=video.VIDEO_PARAMETERS['resolution'],
                    duration=video.VIDEO_PARAMETERS['duration'],audio=video.VIDEO_PARAMETERS['audio'],estimatedCny=4.8)

    def validate_configuration(self):video.headers()

    def build_request(self,job,image_path):return video.payload(job,image_path)

    async def submit(self,job,body):
        async with httpx.AsyncClient() as c:
            response=await c.post(video.endpoint()+'/services/aigc/video-generation/video-synthesis',headers=video.headers(True),json=body)
            response.raise_for_status();return response.json()['output']['task_id']

    async def inspect(self,job):
        async with httpx.AsyncClient() as c:
            response=await c.get(video.endpoint()+'/tasks/'+job['remoteId'],headers=video.headers())
            response.raise_for_status();result=response.json()['output']
            if result['task_status']=='SUCCEEDED':return dict(status='succeeded',url=result['video_url'])
            if result['task_status'] in ('FAILED','CANCELED'):return dict(status='failed')
            return dict(status='running')

    async def download(self,job,result):
        async with httpx.AsyncClient() as c:
            response=await c.get(result['url']);response.raise_for_status();return response.content
