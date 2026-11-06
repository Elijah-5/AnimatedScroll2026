/** User-initiated, single-frame capture; all capture tracks stop before editing. */
export async function captureScreen():Promise<string>{
 if(!navigator.mediaDevices?.getDisplayMedia)throw Error('当前浏览器不支持直接截图，请粘贴系统截图或选择图片。')
 const stream=await navigator.mediaDevices.getDisplayMedia({video:true,audio:false,preferCurrentTab:true} as DisplayMediaStreamOptions)
 const video=document.createElement('video');video.muted=true;video.playsInline=true
 try{
  video.srcObject=stream;await video.play()
  await new Promise<void>((resolve,reject)=>{if(video.videoWidth){resolve();return}video.onloadeddata=()=>resolve();video.onerror=()=>reject(Error('截图画面未能载入'))})
  await new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())))
  const canvas=document.createElement('canvas');canvas.width=video.videoWidth;canvas.height=video.videoHeight
  if(!canvas.width||!canvas.height)throw Error('未取得截图画面，请重试')
  canvas.getContext('2d')!.drawImage(video,0,0);return canvas.toDataURL('image/png')
 }finally{stream.getTracks().forEach(track=>track.stop());video.srcObject=null}
}
