<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import SmartEditButton from './SmartEditButton.vue'
import {selectFiltered} from './smartEditRuntime'
const props=defineProps<{kind:string;rows:any[];label:string}>(),query=ref(''),selected=ref<string[]>([])
const filtered=computed(()=>props.rows.filter(r=>(r.draft.name||r.draft.title||r.id).includes(query.value)))
watch(()=>props.rows.map(r=>r.id).join(','),()=>selected.value=selected.value.filter(id=>props.rows.some(r=>r.id===id)))
</script>
<template><details class="smart-batch"><summary>批量智能修改<span v-if="selected.length"> · 已选 {{selected.length}} 项</span></summary><div class="batch-toolbar"><input v-model="query" :aria-label="'筛选'+label" :placeholder="'搜索'+label"><button @click="selected=selectFiltered(selected,filtered.map(r=>r.id),true)">全选筛选结果</button><button @click="selected=[]">取消选择</button><SmartEditButton :kind="kind" :item-ids="selected" :label="'所选'+label"/></div><div class="batch-options"><label v-for="row in filtered" :key="row.id"><input type="checkbox" :value="row.id" v-model="selected">{{row.draft.name||row.draft.title||row.id}}</label></div></details></template>
<style scoped>.smart-batch{margin:12px 0 18px;padding:11px 14px;border:1px solid #e0e7da;border-radius:8px;background:#fafcf6}.smart-batch summary{font-size:11px;color:#74866a;cursor:pointer}.batch-toolbar{display:flex;gap:8px;align-items:center;margin:13px 0}.batch-toolbar input{flex:1;font-size:12px}.batch-toolbar button{font-size:11px;white-space:nowrap}.batch-options{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;max-height:230px;overflow:auto}.batch-options label{display:flex;gap:7px;align-items:center;font-size:12px;margin:0}.batch-options input{width:auto}</style>
