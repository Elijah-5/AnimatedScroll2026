import {inject} from 'vue'
import {routeNames} from './navigation'
export function useStudio():any{return inject('studio')}
export const names=routeNames
export const states:Record<string,string>={enabled:'AI默认 · 已启用',manual_enabled:'人工编辑 · 已启用',draft:'待准备',waiting:'等待前置条件',confirmed:'已确认',stale:'输入失效',review:'待复核',changed:'改动待处理',missing:'待输入',incomplete:'尚未完备',queued:'等待生成',running:'生成中',failed:'生成失败',interrupted:'任务中断'}
export function dirty(r:any){return !r.published||JSON.stringify(r.draft)!==JSON.stringify(r.published)}
export function state(r:any){return r.published&&dirty(r)?'changed':r.published&&r.activation?.method==='auto'?'enabled':r.published&&r.activation?.method==='manual'?'manual_enabled':r.state}
export function id(){return crypto.randomUUID().slice(0,12)}
