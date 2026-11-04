"""Eight history business tables. One work per project; no cross-project identity merge."""
TABLES={
 'works':dict(label='画作档案概述',fields=dict(id='编号',title='画作名称',artist='著录作者',circulation='画作自身流传',story_one_liner='一句话故事')),
 'background_episodes':dict(label='历史背景',fields=dict(id='编号',work_id='画作',phase='时段',summary='背景概述',sort_order='排序')),
 'persons':dict(label='人物',fields=dict(id='编号',canonical_name='通行姓名')),
 'work_persons':dict(label='画作与人物',fields=dict(work_id='画作',person_id='人物',presence='画中范围',character_id='关联创作人物（选填）')),
 'person_lines':dict(label='人物画像句子',fields=dict(id='编号',work_id='画作',person_id='人物',aspect='画像方面',line_text='画像句子',grounding='依据类型',quotation_id='史书原话',inference_id='研究推断',sort_order='排序')),
 'hist_sources':dict(label='史书书目与版本',fields=dict(id='编号',title='书名',genre='体裁',edition='具体版本',resource_uri='版本原文位置',snapshot_text='该版本核对文本',content_hash='核对文本SHA-256',verification_note='核对说明')),
 'quotations':dict(label='史书原话',fields=dict(id='编号',source_id='书目版本',work_id='画作',episode_id='背景事件（选填）',locator='卷页定位',original_text='逐字原文',source_start='原文起点',source_end='原文终点')),
 'inferences':dict(label='历史推断',fields=dict(id='编号',work_id='画作',author='判断作者',publication='发表出处',publication_locator='论文页码／位置',claim='判断内容',quotation_id='所解释的史书原话')),
}
ENUMS=dict(phase=['前因','画中','后续'],presence=['画中','画外'],aspect=['身份','行事','言语','关系','史书刻画'],grounding=['原话','推断'],genre=['经传','正史','编年','纪事本末'])
NUMBERS={'sort_order','source_start','source_end'}
NULLABLE={'episode_id','quotation_id','inference_id'}
DELETE_ORDER=('person_lines','inferences','quotations','work_persons','background_episodes','persons','hist_sources','works')
INSERT_ORDER=('works','background_episodes','persons','work_persons','hist_sources','quotations','inferences','person_lines')


def columns(table):return ['project_id']+list(TABLES[table]['fields'])+['revision']


def schema(conn):
    """MySQL creates the same model through storage.mysql_engine metadata."""
    for table in INSERT_ORDER:
        definitions=['project_id TEXT NOT NULL REFERENCES projects(id)']
        for name in TABLES[table]['fields']:
            dtype='INTEGER' if name in NUMBERS else 'TEXT'
            null='' if name in NULLABLE else ' NOT NULL'
            definitions.append(name+' '+dtype+null)
        definitions.append('revision INTEGER NOT NULL CHECK(revision>0)')
        if table=='work_persons':definitions.append('PRIMARY KEY(work_id,person_id)')
        else:definitions.append('PRIMARY KEY(id)' if table=='works' else 'PRIMARY KEY(project_id,id)');definitions.append('UNIQUE(project_id,id)')
        if 'work_id' in TABLES[table]['fields']:definitions.append('CHECK(work_id=project_id)');definitions.append('FOREIGN KEY(work_id) REFERENCES works(id)')
        for name,values in ENUMS.items():
            if name in TABLES[table]['fields']:definitions.append('CHECK('+name+' IN ('+','.join("'"+v+"'" for v in values)+'))')
        if table=='works':definitions.append('CHECK(id=project_id)')
        if table=='work_persons':definitions.append('FOREIGN KEY(project_id,person_id) REFERENCES persons(project_id,id)')
        if table=='quotations':
            definitions+=['FOREIGN KEY(project_id,source_id) REFERENCES hist_sources(project_id,id)','FOREIGN KEY(project_id,episode_id) REFERENCES background_episodes(project_id,id)']
        if table=='inferences':definitions.append('FOREIGN KEY(project_id,quotation_id) REFERENCES quotations(project_id,id)');definitions.append('CHECK(quotation_id IS NOT NULL)')
        if table=='person_lines':
            definitions+=['FOREIGN KEY(work_id,person_id) REFERENCES work_persons(work_id,person_id)','FOREIGN KEY(project_id,quotation_id) REFERENCES quotations(project_id,id)','FOREIGN KEY(project_id,inference_id) REFERENCES inferences(project_id,id)',"CHECK((grounding='原话' AND quotation_id IS NOT NULL AND inference_id IS NULL) OR (grounding='推断' AND inference_id IS NOT NULL AND quotation_id IS NULL))"]
        conn.execute('CREATE TABLE IF NOT EXISTS '+table+' ('+','.join(definitions)+')')


def mysql_tables(meta,table,key,text):
    from sqlalchemy import Column,String,Integer,ForeignKeyConstraint,UniqueConstraint,CheckConstraint
    for name in INSERT_ORDER:
        cols=[Column('project_id',String(128),primary_key=name not in ('works','work_persons'),nullable=False,index=True)]
        for field in TABLES[name]['fields']:
            if field in NUMBERS:col=Column(field,Integer,nullable=False)
            elif field=='id' or field.endswith('_id'):col=Column(field,String(128),primary_key=field=='id' or name=='work_persons' and field in ('work_id','person_id'),nullable=field in NULLABLE)
            elif field in ENUMS:col=Column(field,String(32),nullable=False)
            else:col=text(field)
            cols.append(col)
        cols.append(Column('revision',Integer,nullable=False))
        constraints=[ForeignKeyConstraint(['project_id'],['projects.id']),CheckConstraint('revision>0')]
        if name!='work_persons':constraints.append(UniqueConstraint('project_id','id'))
        if 'work_id' in TABLES[name]['fields']:constraints.extend([CheckConstraint('work_id=project_id'),ForeignKeyConstraint(['work_id'],['works.id'])])
        if name=='works':constraints.append(CheckConstraint('id=project_id'))
        if name=='work_persons':constraints.append(ForeignKeyConstraint(['project_id','person_id'],['persons.project_id','persons.id']))
        if name=='quotations':constraints.extend([ForeignKeyConstraint(['project_id','source_id'],['hist_sources.project_id','hist_sources.id']),ForeignKeyConstraint(['project_id','episode_id'],['background_episodes.project_id','background_episodes.id'])])
        if name=='inferences':constraints.extend([ForeignKeyConstraint(['project_id','quotation_id'],['quotations.project_id','quotations.id']),CheckConstraint('quotation_id IS NOT NULL')])
        if name=='person_lines':constraints.extend([ForeignKeyConstraint(['work_id','person_id'],['work_persons.work_id','work_persons.person_id']),ForeignKeyConstraint(['project_id','quotation_id'],['quotations.project_id','quotations.id']),ForeignKeyConstraint(['project_id','inference_id'],['inferences.project_id','inferences.id']),CheckConstraint("(grounding='原话' AND quotation_id IS NOT NULL AND inference_id IS NULL) OR (grounding='推断' AND inference_id IS NOT NULL AND quotation_id IS NULL)")])
        for field,values in ENUMS.items():
            if field in TABLES[name]['fields']:constraints.append(CheckConstraint(field+' IN ('+','.join("'"+v+"'" for v in values)+')'))
        table(name,*cols,*constraints)
