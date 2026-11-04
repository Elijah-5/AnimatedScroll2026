# 步辇图：真实 API 验收与恢复

日期：2026-11-01。使用本机已经更新的 AIHubMix Key；未向聊天、前端、报告或导出包写入密钥。此处的“确认”仅为用户授权的隔离副本技术验收，不代表史学审核完成。

## 验收环境

| 项目 | 结果 |
|---|---|
| 独立项目 | 313591d1a9a2，版本 147 |
| 数据目录 | data/acceptance/20261101-live/data；与原 data/projects.sqlite 分离 |
| 原始材料 | 复制步辇图(2)的原画及25页PDF，重新解析、重新调用模型；未复用旧LLM整理结果 |
| 文本／视觉 | AIHubMix DeepSeek / gpt-4o |
| 请求预算 | 62 / 100；含格式修复和失败尝试 |
| HTTP结果 | 61 条有响应；1 条未确认传输结果，保守计入预算（包含沙箱DNS失败） |
| 累计服务端 token 计量 | {"prompt_tokens": 1291752, "completion_tokens": 73624, "total_tokens": 1365376}；没有价格数据，不据此估算费用 |
| 视频 | 0条远端任务，未请求付费视频；播放使用显式本地占位文件 |
| MySQL | DDL编译通过；SQLite替代目标覆盖全表迁移、非空拒绝与核对；未连接真实MySQL，未执行迁移 |

## 真实流程结果

| 步骤 | 结果 |
|---|---|
| 原始导入 | 25页、29524字符，本地解析 |
| 文献整理 | 142条引用条目，12次模型请求；无效原文引用不采用 |
| 本地检测与真实视觉 | 13个候选框，7个高把握对应经技术核对，其余保持未确认 |
| 角色核对 | 依据PDF原页补充太宗、红衣与白衣官员的画中范围；去除三条重复群体／称谓角色，保留5个角色。官职推测保留限定语。 |
| 历史八表 | 已确认版本r2；works=1、background_episodes=3、persons=2、work_persons=2、person_lines=4、hist_sources=1、quotations=4、inferences=1 |
| 制作 | 16条线索、1段剧情、5个人物知识；16个有效已确认分镜 |
| 视频提示词 | 每个分镜预览、保存及审核成功；真实参数wan3.0-video／480P／5秒／音频开启／prompt_extend=false，未提交生成 |
| 体验对话 | 三次真实提问覆盖身份、画中事件及知识范围外问题；范围外返回不知情，无线索解锁 |
| 记线索与恢复 | 记录2条线索，解锁2个分镜；重复requestId返回原结果且无新增模型请求；会话可重新读取，制作版本不变 |
| 播放与导出 | 本地占位MP4读取、草稿叙事ZIP、素材及解锁关系通过；占位标为placeholder/local_fixture，不写入video_jobs，不用于正式视频选择 |
| 一致性建议 | 22条，待创作者审查；没有把技术验收当作历史内容发布批准 |

本次修复了真实调用暴露的问题：生成引用现在会先校验再进入修复流程；知识绑定使用显式短编号映射避免抄错ID；删除人物同时将其知识标为删除历史，避免遗留孤立待办。历史编辑接入全局保存，在浏览器切页后仍保留草稿。

## 史料与研究边界

《旧唐书》原话来自维基文库数字转录的206字句段快照。记录了页面位置、取得日期、固定链接所示修订编号、快照哈希和逐字偏移。直接下载为403，固定修订页面未能再次读取，未声称核对纸本或固定修订全文；四库版未取得正文，因此没有冒充已经核对四库版。版本说明保留在hist_sources.verification_note。

现代论文为谢继胜、朱姝纯《关于〈步辇图〉研究的几个问题》，《故宫博物院院刊》2018年第4期；作者和题名按原PDF首页核对。作者归属争议、官员官职、武则天可能在侧等保留为研究说明；没有为了填满表格补造原话。背景时段及“进对合旨”的分类在技术核对中修正；更细的历史内容仍需创作者／研究者审查。

## 验证与文件

- 后端195项测试、前端23项状态测试及Vue类型检查／生产构建通过。
- 覆盖同名项目隔离、真实外键、原话逐字匹配、依据互斥、事务回滚、版本冲突、草稿隔离、并行编辑、视频精确依赖、任务去重和重启不重提。
- Agent回归覆盖越权请求、无效线索、失效知识、群体共享、失败恢复和收集后解锁。空项目及非折槛项目由隔离回归覆盖。
- 浏览器验证八表展示、切页保存、差异预览；另一次真实对话、记线索、5秒播放、刷新恢复进度和返回原分镜页面全部通过。刷新后返回位置按项目保存，不改变制作数据。截图见docs/ui/history-eight-tables.png与docs/ui/live-dialogue-placeholder.png。
- 原有3个项目及events/tasks/studio_jobs/document_cache与实施前备份逐行一致；10个原资产哈希一致。github-version-2未编辑，未自动commit或push。

| 文件 | 用途 |
|---|---|
| data/acceptance/20261101-live/state.json | 阶段结果、人工技术核对、体验会话结果 |
| data/acceptance/20261101-live/requests.json | 请求次数、模型、HTTP状态、耗时与token，无密钥和请求正文 |
| data/acceptance/20261101-live/verification-summary.json | 原项目保护核对及验证摘要 |
| data/acceptance/20261101-live/history-eight-tables.json | 本次独立项目八表数据，含版本核对快照 |
| data/acceptance/20261101-live/narrative-with-test-placeholder.zip | 已确认制作内容的草稿包，包含标记清楚的测试占位视频，无实时模型服务 |

## 启停与 Key

在creation-agent-demo目录执行：

```sh
.venv/bin/python scripts/configure_api.py
.venv/bin/python scripts/server_control.py restart
.venv/bin/python scripts/server_control.py status
# 日常启动／关闭
.venv/bin/python scripts/server_control.py start
.venv/bin/python scripts/server_control.py stop
```

配置命令必须在本地终端交互输入，不回显Key。也可双击配置API、重启服务器、查看服务状态等.command文件。旧环境变量不会盖过本目录.env；视频Key不会切换前期模型。

## 备份与恢复

实施前完整源码及data备份位于`../merge-backups/history-20261101-003956/creation-agent-demo`，文件清单与SHA-256在同级manifest.json，共227文件。备份目录权限700，包含本机.env，勿分享。更早的合并前备份仍保留在`../merge-backups/20261031-235253`。

恢复时先停止服务，保留当前目录，再从备份复制为原目录名。下面命令是恢复说明，本轮未执行：

```sh
# 先在creation-agent-demo中
.venv/bin/python scripts/server_control.py stop
cd ..
mv creation-agent-demo creation-agent-demo.after-history-merge
ditto merge-backups/history-20261101-003956/creation-agent-demo creation-agent-demo
```

上面的备份位置实际在当前Projects目录的merge-backups；若从Projects执行，使用`merge-backups/...`。依赖、模型和dist未纳入源码备份；可从保留目录复用node_modules、.venv和models，或按README安装后构建。完整data已备份，不需要MySQL迁移。恢复后检查本地.env与服务状态，再启动。

正式工作台已使用更新后的控制命令重启，8000／5173状态为当前代码和配置，运行任务为无；原数据复核仍一致。临时8017／5187验收服务已关闭。
