<script setup lang="ts">
import {computed,nextTick,onMounted,onUnmounted,ref} from 'vue'
import {narrationSentences} from './experiencePresentation'
const props=defineProps<{media:any;image:string}>(),emit=defineEmits<{close:[]}>()
const video=ref<HTMLVideoElement>(),paused=ref(false),index=ref(0),voiceError=ref(''),playError=ref('')
const sentences=computed(()=>narrationSentences(props.media.narrationText||''))
const subtitle=computed(()=>sentences.value[index.value]||'')
const region=computed(()=>props.media.region||props.media.storyboard?.region||{x:0,y:0,w:1,h:1})
const cropStyle=computed(()=>({width:100/region.value.w+'%',maxWidth:'none',left:-100*region.value.x/region.value.w+'%',top:-100*region.value.y/region.value.h+'%',height:100/region.value.h+'%'}))
let sequence=0,utterance:SpeechSynthesisUtterance|undefined,disposed=false,timeout:ReturnType<typeof setTimeout>|undefined
const speech=()=>typeof window!=='undefined'&&'speechSynthesis' in window?window.speechSynthesis:null
function cancel(){sequence++;clearTimeout(timeout);speech()?.cancel();utterance=undefined;video.value?.pause()}
function speak(token:number){
 if(disposed||token!==sequence||index.value>=sentences.value.length)return
 const synth=speech(),voice=synth?.getVoices().find(v=>/^zh(-|_)/i.test(v.lang)&&v.localService)
 if(!synth||!voice){voiceError.value='设备没有可用的本地中文语音，当前显示文字讲解。';return}
 const u=new SpeechSynthesisUtterance(sentences.value[index.value]);utterance=u;u.voice=voice;u.lang=voice.lang;u.rate=.95
 u.onend=()=>{if(token===sequence&&!paused.value){index.value++;speak(token)}}
 u.onerror=(event)=>{if(token===sequence&&event.error!=='canceled'&&event.error!=='interrupted')voiceError.value='中文朗读未能开始，可点击重播；文字讲解仍可阅读。'}
 synth.speak(u)
}
async function start(){
 cancel();paused.value=false;index.value=0;voiceError.value='';playError.value='';const token=sequence
 await nextTick();if(disposed||token!==sequence)return
 if(video.value){video.value.currentTime=0;try{await video.value.play()}catch{playError.value='浏览器暂未开始播放，请点击“播放／继续”。'}}
 if(!speech()?.getVoices().length){timeout=setTimeout(()=>speak(token),350)}else speak(token)
}
async function toggle(){
 if(paused.value||playError.value){paused.value=false;playError.value='';speech()?.resume();if(!utterance)speak(sequence);try{await video.value?.play()}catch{playError.value='无法播放视频，可重播或阅读讲解。'}}
 else{paused.value=true;speech()?.pause();video.value?.pause()}
}
function close(){cancel();emit('close')}
function hidden(){if(document.hidden&&!paused.value){paused.value=true;speech()?.pause();video.value?.pause()}}
onMounted(()=>{void start();document.addEventListener('visibilitychange',hidden)})
onUnmounted(()=>{disposed=true;cancel();document.removeEventListener('visibilitychange',hidden)})
</script>
<template><section class="narrative-player" :class="{paused}" role="region" :aria-label="media.title+'分镜讲解'">
 <header><b>{{media.title}}</b><button @click="close" aria-label="关闭分镜讲解">×</button></header>
 <div class="narrative-frame"><video v-if="media.videoUrl" ref="video" :src="media.videoUrl" muted playsinline preload="auto" @error="playError='视频载入失败，可关闭后重播或阅读讲解。'"/><img v-else-if="media.imageUrl" class="generated-image" :src="media.imageUrl" :alt="media.title"/><div v-else class="painting-crop"><img :src="image" :style="cropStyle" :alt="media.title+'对应原画区域'"/></div></div>
 <small>{{media.mediaLabel||(media.videoUrl?'分镜视频':'原画局部预览（非生成画面）')}}</small>
 <p class="narrative-subtitle" aria-live="polite">{{voiceError?media.narrationText:subtitle||media.narrationText}}</p>
 <p v-if="voiceError||playError" class="playback-note" role="status">{{voiceError||playError}}</p>
 <details><summary>完整讲解</summary><p>{{media.narrationText}}</p></details>
 <footer><button @click="toggle">{{paused||playError?'播放／继续':'暂停'}}</button><button @click="start">重播</button><button @click="close">关闭并返回全景</button></footer>
</section></template>
<style scoped>
.narrative-player{pointer-events:auto;width:min(86%,620px);max-height:94%;overflow:auto;background:#fffcf3f5;border:1px solid #d6c7a6;border-radius:12px;box-shadow:0 12px 40px #302d2860;line-height:1.6;color:#3e473b}.narrative-player header{display:flex;justify-content:space-between;align-items:center;padding:8px 14px}.narrative-player header button{background:none;border:0;font-size:20px}.narrative-frame{width:100%;height:clamp(110px,15vw,220px);overflow:hidden;background:#e6dfcd}.narrative-frame video,.generated-image{width:100%;height:100%;object-fit:contain}.generated-image,.painting-crop{animation:slow-push 18s linear both}.paused .generated-image,.paused .painting-crop{animation-play-state:paused}.painting-crop{position:relative;width:100%;height:100%;overflow:hidden}.painting-crop img{position:absolute;object-fit:fill}.narrative-player>small{display:block;padding:4px 14px;font-size:10px;color:#8b7f67}.narrative-subtitle{padding:0 16px;margin:6px 0;font-size:14px;min-height:40px}.narrative-player details{font-size:11px;padding:0 16px}.narrative-player details p{white-space:pre-wrap}.playback-note{font-size:11px;color:#8e672c;padding:0 16px}.narrative-player footer{display:flex;gap:8px;padding:10px 14px}.narrative-player footer button{font-size:11px;padding:5px 10px}@keyframes slow-push{from{transform:scale(1)}to{transform:scale(1.08)}}@media(prefers-reduced-motion:reduce){.generated-image,.painting-crop{animation:none}}
</style>
