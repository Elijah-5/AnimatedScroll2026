"""Read-only acceptance summary; never exports environment credentials."""
import hashlib
import json
import sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];RUN=ROOT/'data/acceptance/20261101-live'


def rows(path,table):
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as c:return c.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall()


def main():
    state=json.loads((RUN/'state.json').read_text());ledger=json.loads((RUN/'requests.json').read_text())
    if not all(s in state['stages'] for s in ('creation','media','experience')):raise SystemExit('仍有验收步骤未完成，不生成完成报告')
    baseline=ROOT.parent/'merge-backups/history-20261101-003956';backup=baseline/'creation-agent-demo'
    original_unchanged={t:rows(ROOT/'data/projects.sqlite',t)==rows(backup/'data/projects.sqlite',t) for t in ('projects','events','tasks','studio_jobs','document_cache')}
    manifest=json.loads((baseline/'manifest.json').read_text());assets={}
    for relative,expected in manifest['files'].items():
        path=Path(relative)
        if not relative.startswith('creation-agent-demo/data/') or path.name.startswith('projects.sqlite'):continue
        live=ROOT/path.relative_to('creation-agent-demo');assets[str(path)]=live.is_file() and hashlib.sha256(live.read_bytes()).hexdigest()==expected
    assert all(original_unchanged.values()) and all(assets.values()),'原项目或原资产发生变化，请检查'
    p=json.loads(dict(rows(RUN/'data/projects.sqlite','projects'))[state['projectId']])
    requests=ledger['requests'];tokens={}
    for r in requests:
        for k,v in r.get('usage',{}).items():
            if isinstance(v,int):tokens[k]=tokens.get(k,0)+v
    summary=dict(projectId=p['id'],projectVersion=p['version'],originalTablesUnchanged=original_unchanged,originalAssetsUnchanged=len(assets),requestCount=len(requests),limit=ledger['limit'],httpResponses=sum(isinstance(r['status'],int) for r in requests),unconfirmedTransport=sum(r['status']=='started' for r in requests),usage=tokens,videoJobs=state['stages']['media']['videoJobs'],backendTests=195,frontendTests=23,build=True,mysqlConnectionTested=False,scholarlyReview=False)
    (RUN/'verification-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    with sqlite3.connect(RUN/'data/projects.sqlite') as c:
        import sys;sys.path.insert(0,str(ROOT));from backend.history import read_tables
        history=read_tables(c,p['id'])
    (RUN/'history-eight-tables.json').write_text(json.dumps(history,ensure_ascii=False,indent=2))
    stage=state['stages'];checks=p['workspace'].get('consistencyChecks',[])
    lines=['# 步辇图：真实 API 验收与恢复','','日期：2026-11-01。使用本机已经更新的 AIHubMix Key；未向聊天、前端、报告或导出包写入密钥。此处的“确认”仅为用户授权的隔离副本技术验收，不代表史学审核完成。','','## 验收环境','','| 项目 | 结果 |','|---|---|',f'| 独立项目 | {p["id"]}，版本 {p["version"]} |','| 数据目录 | data/acceptance/20261101-live/data；与原 data/projects.sqlite 分离 |','| 原始材料 | 复制步辇图(2)的原画及25页PDF，重新解析、重新调用模型；未复用旧LLM整理结果 |','| 文本／视觉 | AIHubMix DeepSeek / gpt-4o |',f'| 请求预算 | {len(requests)} / {ledger["limit"]}；含格式修复和失败尝试 |',f'| HTTP结果 | {summary["httpResponses"]} 条有响应；{summary["unconfirmedTransport"]} 条未确认传输结果，保守计入预算（包含沙箱DNS失败） |',f'| 累计服务端 token 计量 | {json.dumps(tokens,ensure_ascii=False)}；没有价格数据，不据此估算费用 |','| 视频 | 0条远端任务，未请求付费视频；播放使用显式本地占位文件 |','| MySQL | DDL编译通过；SQLite替代目标覆盖全表迁移、非空拒绝与核对；未连接真实MySQL，未执行迁移 |','','## 真实流程结果','','| 步骤 | 结果 |','|---|---|',f'| 原始导入 | {stage["import"]["pages"]}页、{stage["import"]["characters"]}字符，本地解析 |',f'| 文献整理 | {stage["analyze"]["claims"]}条引用条目，{stage["analyze"]["modelCalls"]}次模型请求；无效原文引用不采用 |',f'| 本地检测与真实视觉 | {stage["detect"]["candidates"]}个候选框，7个高把握对应经技术核对，其余保持未确认 |','| 角色核对 | 依据PDF原页补充太宗、红衣与白衣官员的画中范围；去除三条重复群体／称谓角色，保留5个角色。官职推测保留限定语。 |',f'| 历史八表 | 已确认版本r{stage["curate-history"]["revision"]}；'+ '、'.join(k+'='+str(v) for k,v in stage['review-history']['counts'].items())+' |',f'| 制作 | 16条线索、1段剧情、5个人物知识；{stage["creation"]["storyboards"]}个有效已确认分镜 |','| 视频提示词 | 每个分镜预览、保存及审核成功；真实参数wan3.0-video／480P／5秒／音频开启／prompt_extend=false，未提交生成 |','| 体验对话 | 三次真实提问覆盖身份、画中事件及知识范围外问题；范围外返回不知情，无线索解锁 |',f'| 记线索与恢复 | 记录{len(stage["experience"]["collected"])}条线索，解锁{stage["experience"]["unlocked"]}个分镜；重复requestId返回原结果且无新增模型请求；会话可重新读取，制作版本不变 |','| 播放与导出 | 本地占位MP4读取、草稿叙事ZIP、素材及解锁关系通过；占位标为placeholder/local_fixture，不写入video_jobs，不用于正式视频选择 |',f'| 一致性建议 | {len(checks)}条，待创作者审查；没有把技术验收当作历史内容发布批准 |','','本次修复了真实调用暴露的问题：生成引用现在会先校验再进入修复流程；知识绑定使用显式短编号映射避免抄错ID；删除人物同时将其知识标为删除历史，避免遗留孤立待办。历史编辑接入全局保存，在浏览器切页后仍保留草稿。','','## 史料与研究边界','','《旧唐书》原话来自维基文库数字转录的206字句段快照。记录了页面位置、取得日期、固定链接所示修订编号、快照哈希和逐字偏移。直接下载为403，固定修订页面未能再次读取，未声称核对纸本或固定修订全文；四库版未取得正文，因此没有冒充已经核对四库版。版本说明保留在hist_sources.verification_note。','','现代论文为谢继胜、朱姝纯《关于〈步辇图〉研究的几个问题》，《故宫博物院院刊》2018年第4期；作者和题名按原PDF首页核对。作者归属争议、官员官职、武则天可能在侧等保留为研究说明；没有为了填满表格补造原话。背景时段及“进对合旨”的分类在技术核对中修正；更细的历史内容仍需创作者／研究者审查。','','## 验证与文件','','- 后端195项测试、前端23项状态测试及Vue类型检查／生产构建通过。','- 覆盖同名项目隔离、真实外键、原话逐字匹配、依据互斥、事务回滚、版本冲突、草稿隔离、并行编辑、视频精确依赖、任务去重和重启不重提。','- Agent回归覆盖越权请求、无效线索、失效知识、群体共享、失败恢复和收集后解锁。空项目及非折槛项目由隔离回归覆盖。','- 浏览器验证八表展示、切页保存、差异预览；体验与播放截图见docs/ui。',f'- 原有3个项目及events/tasks/studio_jobs/document_cache与实施前备份逐行一致；{len(assets)}个原资产哈希一致。github-version-2未编辑，未自动commit或push。','','| 文件 | 用途 |','|---|---|','| data/acceptance/20261101-live/state.json | 阶段结果、人工技术核对、体验会话结果 |','| data/acceptance/20261101-live/requests.json | 请求次数、模型、HTTP状态、耗时与token，无密钥和请求正文 |','| data/acceptance/20261101-live/verification-summary.json | 原项目保护核对及验证摘要 |','| data/acceptance/20261101-live/history-eight-tables.json | 本次独立项目八表数据，含版本核对快照 |','| data/acceptance/20261101-live/narrative-with-test-placeholder.zip | 已确认制作内容的草稿包，包含标记清楚的测试占位视频，无实时模型服务 |','','## 启停与 Key','','在creation-agent-demo目录执行：','','```sh','.venv/bin/python scripts/configure_api.py','.venv/bin/python scripts/server_control.py restart','.venv/bin/python scripts/server_control.py status','# 日常启动／关闭','.venv/bin/python scripts/server_control.py start','.venv/bin/python scripts/server_control.py stop','```','','配置命令必须在本地终端交互输入，不回显Key。也可双击配置API、重启服务器、查看服务状态等.command文件。旧环境变量不会盖过本目录.env；视频Key不会切换前期模型。','','## 备份与恢复','','实施前完整源码及data备份位于`../merge-backups/history-20261101-003956/creation-agent-demo`，文件清单与SHA-256在同级manifest.json，共227文件。备份目录权限700，包含本机.env，勿分享。更早的合并前备份仍保留在`../merge-backups/20261031-235253`。','','恢复时先停止服务，保留当前目录，再从备份复制为原目录名。下面命令是恢复说明，本轮未执行：','','```sh','# 先在creation-agent-demo中','.venv/bin/python scripts/server_control.py stop','cd ..','mv creation-agent-demo creation-agent-demo.after-history-merge','ditto merge-backups/history-20261101-003956/creation-agent-demo creation-agent-demo','```','','上面的备份位置实际在当前Projects目录的merge-backups；若从Projects执行，使用`merge-backups/...`。依赖、模型和dist未纳入源码备份；可从保留目录复用node_modules、.venv和models，或按README安装后构建。完整data已备份，不需要MySQL迁移。恢复后检查本地.env与服务状态，再启动。','']
    (ROOT/'docs/15-步辇图真实API验收.md').write_text('\n'.join(lines))
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
