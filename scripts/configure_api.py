"""Interactive local credential entry. Keys never appear in arguments or stdout."""
import getpass
import os
import shutil
from datetime import datetime
from pathlib import Path
from dotenv import dotenv_values,set_key

ROOT=Path(__file__).resolve().parents[1]


def configure(root=ROOT,read_secret=getpass.getpass):
    if not os.isatty(0):raise ValueError('请在终端运行配置命令，密钥不通过聊天或命令参数传递')
    path=root/'.env';existing=dotenv_values(path) if path.exists() else {}
    print('配置本项目 AIHubMix 文本／视觉 Key。输入隐藏；直接回车保留现有值。')
    key=read_secret('新 AIHubMix API Key：').strip()
    if not key:
        print('未修改现有 Key。');return False
    if any(c in key for c in '\r\n\x00'):raise ValueError('Key不能包含换行或空字符')
    if path.exists():
        folder=root/'.runtime/private-env-backups';folder.mkdir(parents=True,exist_ok=True);folder.chmod(0o700)
        backup=folder/('env-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));shutil.copyfile(path,backup);backup.chmod(0o600)
    else:path.touch(mode=0o600)
    set_key(path,'AIHUBMIX_API_KEY',key,quote_mode='always')
    if not existing.get('MODEL_PROVIDER'):set_key(path,'MODEL_PROVIDER','aihubmix')
    path.chmod(0o600)
    print('已保存本机配置，其他设置保留。请运行“重启服务器.command”使新Key生效。')
    return True


if __name__=='__main__':
    try:configure()
    except (KeyboardInterrupt,EOFError):print('\n已取消，未继续配置。')
    except ValueError as exc:print(str(exc));raise SystemExit(1)
