<script setup lang="ts">
import {ref,computed} from 'vue'
const props=defineProps<{folder:any,folders:any[],clues:any[],selected:string}>();const emit=defineEmits(['select','folder']);const open=ref(true)
const children=computed(()=>props.folders.filter(f=>f.parentId===props.folder.id))
function authenticity(r:any){const u=r.draft.units||[];return u.some((u:any)=>u.category==='fiction')?'fiction':u.some((u:any)=>u.category==='inference')?'inference':'supported'}
</script>
<template><div class="tree-folder" :class="folder.type"><button class="folder-name" @click="open=!open" @contextmenu.prevent="emit('folder',folder)">{{open?'▾':'▸'}} {{folder.name}}</button><button class="folder-settings" @click="emit('folder',folder)" aria-label="分类操作">⋯</button><div v-if="open" class="tree-children"><ClueTree v-for="f in children" :folder="f" :folders="folders" :clues="clues" :selected="selected" @select="emit('select',$event)" @folder="emit('folder',$event)"/><button v-for="r in clues.filter(r=>r.draft.parentId===folder.id)" class="clue-node" :class="[r.draft.type,authenticity(r),{selected:selected===r.id}]" @click="emit('select',r.id)">{{r.draft.name}}</button></div></div></template>
