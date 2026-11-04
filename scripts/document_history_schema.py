"""Generate the field reference from the actual eight-table schema."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.history_schema import TABLES,ENUMS,NUMBERS,NULLABLE

DESCRIPTIONS=dict(
 id='本项目内的记录编号。works.id 等于项目编号，其余编号与 project_id 共同唯一。',
 title='画作名称或史书书名，按所在表填写。',artist='著录作者；作者争议另存研究资料，不能无依据定论。',
 circulation='画作作为物品的创作、收藏、流传与现藏信息；不写画中历史事件。',story_one_liner='一句话说明画面表现的事。',
 work_id='指向本项目 works.id，必须等于 project_id。',phase='只填前因、画中、后续；更晚事件另列后续记录。',summary='供页面展示的现代汉语背景概述。',sort_order='从零开始的非负排序数，数字小的在前。',
 canonical_name='通行姓名，如唐太宗、禄东赞；不自动与其他项目的同名人物合并。',person_id='指向本项目 persons.id。',presence='只填画中或画外，区分画面可见人物和故事背景人物。',character_id='可选，显式关联现有创作人物ID；不会另造创作人物或按姓名自动绑定。',
 aspect='只填身份、行事、言语、关系、史书刻画。',line_text='供创作阅读的一句画像；史书评语保留为史书评价，不伪装成客观性格定论。',grounding='只填原话或推断；决定下列两个依据字段中哪一个必填。',quotation_id='本项目 quotations.id。inferences 中必填；person_lines 在 grounding=原话时必填，在推断时为空。',inference_id='本项目 inferences.id；画像依据为推断时必填，原话时为空。',
 genre='只收经传、正史、编年、纪事本末；论文、馆方说明与教材保留为研究资料。',edition='指定的纸本或可识别数字版本。数字转录必须说明范围及核对限制；不能只写书名。',resource_uri='版本原文的 https:// 位置，或 document: 开头的本地文献定位。',snapshot_text='该版本的核对文本或明确标示范围的完整句段节录；不由模型自动编造。',content_hash='服务端计算 snapshot_text 的 UTF-8 SHA-256，不可手改。',verification_note='谁在何时核对、数字版或纸本、未完成事项和版本限制；字段齐全不等于史实已学术确认。',
 source_id='本项目 hist_sources.id，指向一部书的具体版本。',episode_id='可选，本项目 background_episodes.id；人物专用原话可留空。',locator='可找回原文的位置，例如卷一九六上·吐蕃传；需要时补页码、段落。',original_text='指定版本逐字原文，不翻译、不改字、不拼接，不以省略号截断。',source_start='原文在核对文本中的起点，Python Unicode 字符索引，从零开始。',source_end='原文终点，不包含这个位置的字符；snapshot_text[start:end] 必须等于 original_text。',
 author='做出判断的研究者或作者。',publication='论文、专著或文章名称，可与史书书目分开管理。',publication_locator='研究出处的页码、章节或其他定位，可选。',claim='后人的判断本身；必须解释 quotation_id 指向的具体原话。没有合适原话的画作作者争议留在研究备注，不能伪造关联。')

def main():
    lines=['# 历史真实性资料库：融合后的八张表','','这八张表已落地为关系表。SQLite 为默认数据库；MySQL 由明确配置启用，结构通过 SQLAlchemy 定义，本次未做真实 MySQL 连通与迁移。原有项目、任务、视频、体验和文献缓存等持久化表继续保留，不计入这八张业务表。','','## 包含的数据表','','| 内容 | 表 | 表中内容 |','|---|---|---|',
    '| 画作档案概述 | works | 作者、画作自身流传，以及画面故事的一句话。 |',
    '| 历史背景 | background_episodes | 按前因、画中、后续分条保存，不把不同年代事件合成画中同一时刻。 |',
    '| 人物 | persons、work_persons、person_lines | 人物、画中／画外关联及逐句画像，每句区分原话与推断。 |',
    '| 历史资料原话 | hist_sources、quotations | 指定版本书目与逐字原文；现代论文不进入史书书目。 |',
    '| 历史推断 | inferences | 研究者、出处和判断，每条必须指向具体史书原话。 |','','## 共用字段与隔离规则','','每张表均有以下两个附加字段，不重复列入后面的业务字段表。','','| 字段 | 类型 | 含义 |','|---|---|---|','| project_id | TEXT | 所属项目，外键指向 projects.id；所有查询、编辑和关联均限制在该项目。 |','| revision | INTEGER | 已确认行的版本，最小为1；业务内容不变时保留原行版本。 |','','一幅画在每个创作项目中有独立档案。即使两项目都叫《步辇图》，也不共享历史人物或依据。works 的主键为 id，且 id=project_id；work_persons 的主键为 (work_id,person_id)；其余表主键为 (project_id,id)。所有关联受同项目外键约束。SQLite 类型 TEXT 在 MySQL 中按用途映射为 VARCHAR(128)、VARCHAR(32) 或 LONGTEXT。','']
    for name,definition in TABLES.items():
        lines+=['## '+name+' · '+definition['label'],'','| 字段 | SQLite 类型 | 含义 |','|---|---|---|']
        for field in definition['fields']:
            dtype='INTEGER' if field in NUMBERS else 'TEXT'
            if field in NULLABLE:dtype+=' / NULL'
            lines.append('| '+field+' | '+dtype+' | '+DESCRIPTIONS[field]+' |')
        lines.append('')
    lines+=['## 关系与校验','','```mermaid','erDiagram',' works ||--o{ background_episodes : includes',' works ||--o{ work_persons : depicts',' persons ||--o{ work_persons : participates',' work_persons ||--o{ person_lines : describes',' hist_sources ||--o{ quotations : contains',' background_episodes o|--o{ quotations : supports',' quotations ||--o{ inferences : interprets',' quotations o|--o{ person_lines : grounds',' inferences o|--o{ person_lines : grounds','```','','- 确认前校验必填、枚举、同项目关联和逐字定位。草稿可不完整，但不会进入已确认八表。','- person_lines 的依据严格互斥：原话只填 quotation_id；推断只填 inference_id。数据库 CHECK 与外键共同约束。','- quotations 的 episode_id 可空；inferences 的 quotation_id 不可空。不能为了填满八表编造作者、版本、原文或推断。','- 精确字符匹配证明引文来自所提供快照，不能自动证明快照版本可信或内容符合史实；仍需核对版本说明与学术依据。','- 草稿保存在 workspace.historyLibrary，已确认数据保存在八表。确认事务同时写入项目版本和 events 中的前后快照，任何失败均回滚。','','## 页面与制作流程','','古画资料库中的“历史资料库”可编辑八表，定位原文，保存草稿，预览差异并确认。AI 整理只产生建议草稿，只能引用用户提供且已定位的原话ID。缺少依据、研究论文、作者归属争议等保存在“研究备注”，不能自动升级为史实。已有草稿以项目版本和草稿哈希防止覆盖。','','明确点击“采用到资料草稿”后，才向现有资料及显式关联人物写入历史版本快照与带标签的画像。不会创建另一套剧情或按名称复制人物。制作资料、人物、线索和分镜仍须经过现有确认及依赖检查；新历史版本不会静默替换已确认制作内容。人工采用时应先审查相关人物草稿。叙事包只使用已确认制作快照，包含已采用历史版本的书目、原话、知识和解锁关系，不包含整部核对文本、密钥或聊天记录。','','## 《步辇图》组织示例（说明格式，非预置史实）','','| 表 | 示例 |','|---|---|','| works | title=步辇图；artist=著录作者；story_one_liner=唐太宗坐步辇，接见吐蕃使臣禄东赞。作者归属争议另存研究备注。 |','| background_episodes | 前因：请婚与许婚；画中：使者来访；后续：文成公主入藏。若纳入更晚唐蕃会盟，另列后续并补对应原话。 |','| persons / work_persons | 唐太宗、禄东赞标画中；松赞干布、文成公主标画外；只有人工明确关联的画中角色可采用到制作人物。 |','| hist_sources / quotations | 先登记可识别版本、文本快照和定位，再按该版原字录入原话，保留繁简及标点差异。 |','| inferences / person_lines | 画面使者对应史书人物是一条研究判断，须登记研究者与出处，并指向所解释的原话；不能直接写成史书已经确认画面身份。 |','','## API 与迁移','','| 操作 | 路径 |','|---|---|','| 查看八表、字段与草稿 | GET /api/projects/{pid}/history |','| 保存草稿 | PUT /api/projects/{pid}/history/draft |','| 从旧数据建立待审候选 | POST /api/projects/{pid}/history/legacy-candidates |','| 预览／确认／撤回 | POST /api/projects/{pid}/history/preview、confirm、discard |','| 采用到制作草稿 | POST /api/projects/{pid}/history/adopt |','| AI 整理建议 | POST /api/projects/{pid}/studio/jobs，task=history |','','写入均需当前项目 version；草稿保存还需 baseRevision 和 baseDraftHash。迁移脚本覆盖全部持久化表，目标非空时拒绝覆盖，本轮不执行迁移。旧项目的八表起初为空，必须明确建立并审核，不能把现代 PDF 摘要当古籍原文批量灌入。','']
    (ROOT/'docs/14-历史资料库八表结构.md').write_text('\n'.join(lines))

if __name__=='__main__':main()
