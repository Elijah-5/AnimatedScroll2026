import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import ts from 'typescript'
const source=readFileSync(new URL('../src/historyRuntime.ts',import.meta.url),'utf8')
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
const {locateQuotation}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'))
test('quotation positions count Unicode code points like Python',()=>{
 assert.deepEqual(locateQuotation('序𠀀文甲𠀁乙。后','甲𠀁乙。'),{source_start:3,source_end:7})
})
test('quotation matching preserves exact characters and refuses empty or rewritten text',()=>{
 assert.equal(locateQuotation('祿東贊來迎。','禄东赞来迎。'),null)
 assert.equal(locateQuotation('原文。',''),null)
})
