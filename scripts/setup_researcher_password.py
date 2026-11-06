"""Set the local researcher quota password without printing or storing it in code."""
import argparse
import getpass
import os
from pathlib import Path
import re
import secrets
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.video_budget import password_hash


def setup(generate=False):
    env=ROOT/'.env';text=env.read_text() if env.exists() else ''
    if re.search(r'^CREATION_RESEARCHER_PASSWORD_HASH=.+$',text,re.M):
        print('实验员密码已配置，未覆盖现有密码。');return
    password=secrets.token_urlsafe(24) if generate else getpass.getpass('设置实验员密码（至少12个字符）：')
    if len(password)<12:raise ValueError('请使用至少12个字符的密码')
    encoded=password_hash(password)
    line='CREATION_RESEARCHER_PASSWORD_HASH='+encoded
    if re.search(r'^CREATION_RESEARCHER_PASSWORD_HASH=.*$',text,re.M):text=re.sub(r'^CREATION_RESEARCHER_PASSWORD_HASH=.*$',lambda _:line,text,flags=re.M)
    else:text=text.rstrip()+'\n'+line+'\n'
    env.write_text(text)
    if generate:
        folder=ROOT/'.runtime';folder.mkdir(exist_ok=True)
        path=folder/'researcher-password.txt'
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as f:f.write('AnimatedScroll 实验员额度管理密码（仅本机保存，请勿提交版本库）\n'+password+'\n')
        print('已生成本地实验员密码：'+str(path))
    else:print('已保存密码哈希；重启服务后生效。')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--generate',action='store_true');args=parser.parse_args()
    setup(args.generate)
