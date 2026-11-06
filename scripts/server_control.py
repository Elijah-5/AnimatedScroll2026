#!/usr/bin/env python3
"""Manage only this checkout's localhost development services; no credentials in logs."""
import argparse
import hashlib
import sqlite3
from dotenv import dotenv_values
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'
SERVICES = {'backend': 8000, 'frontend': 5173}


def command(pid):
    return subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True).stdout.strip()


def cwd(pid):
    result = subprocess.run(['/usr/sbin/lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'], capture_output=True, text=True)
    return next((line[1:] for line in result.stdout.splitlines() if line.startswith('n')), '')


def ours(pid, name):
    if cwd(pid) != str(ROOT):
        return False
    cmd = command(pid)
    return ('uvicorn backend.main:app' in cmd and '--port 8000' in cmd) if name == 'backend' else ('vite' in cmd and ('--port 5173' in cmd or str(ROOT / 'node_modules') in cmd))


def listeners(port):
    result = subprocess.run(['/usr/sbin/lsof', '-nP', f'-iTCP:{port}', '-sTCP:LISTEN', '-t'], capture_output=True, text=True)
    return [int(p) for p in result.stdout.split() if p.isdigit()]


def signature():
    h=hashlib.sha256()
    for folder in ('backend','src','scripts'):
        for p in sorted((ROOT/folder).rglob('*')):
            if p.is_file() and p.suffix in ('.py','.vue','.ts','.css'):
                h.update(str(p.relative_to(ROOT)).encode());h.update(p.read_bytes())
    for name in ('.env','.env.mysql','package.json','vite.config.ts'):
        path=ROOT/name
        if path.exists():h.update((name+str(path.stat().st_mtime_ns)+str(path.stat().st_size)).encode())
    return h.hexdigest()


def child_environment():
    env=os.environ.copy()
    for name in ('.env','.env.mysql'):
        for key,value in dotenv_values(ROOT/name).items():
            if value is not None and key.startswith(('AIHUBMIX_','DASHSCOPE_','MODEL_','CREATION_','MYSQL_')):env[key]=value
    return env


def active_tasks():
    path=ROOT/'data/projects.sqlite'
    if not path.exists():return []
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as c:
        tables={v[0] for v in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rows=[]
        for table in ('tasks','studio_jobs','feedback_jobs','video_jobs','media_preview_jobs','experiment_runs'):
            if table not in tables:continue
            for body, in c.execute('SELECT body FROM '+table):
                value=json.loads(body)
                if value.get('status',value.get('state')) in ('queued','running','submitting','pending','downloading'):
                    rows.append('用户实验记录' if table=='experiment_runs' else value.get('kind') or value.get('task') or '视频任务')
    folder=ROOT/'data/experience-preparations'
    if folder.exists() and listeners(8000):
        for file in folder.glob('*.json'):
            try:
                job=json.loads(file.read_text())
                if job.get('state') in ('queued','running'):rows.append('体验资源准备')
            except (OSError,ValueError):continue
    return rows


def stale(name):
    path=RUNTIME/f'{name}.json'
    try:return json.loads(path.read_text()).get('signature')!=signature()
    except (ValueError,OSError):return True


def record(name, pid):
    (RUNTIME / f'{name}.json').write_text(json.dumps(dict(pid=pid, command=command(pid),signature=signature())))


def ready(port, name):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}' + ('/api/status' if name == 'backend' else '/'), timeout=1) as response:
            return response.status == 200
    except Exception:
        return False


def start(open_browser=True):
    for name, port in SERVICES.items():
        pids = listeners(port)
        if pids and not all(ours(pid, name) for pid in pids):
            raise RuntimeError(f'端口 {port} 被其他程序占用，未启动或停止任何程序。请先处理端口冲突。')
    if not (ROOT / '.venv/bin/python').exists() or not (ROOT / 'node_modules/vite/bin/vite.js').exists():
        raise RuntimeError('缺少项目依赖，请先按 README 安装 .venv 和 npm 依赖。')
    node = shutil.which('node')
    if not node:
        raise RuntimeError('未找到 Node.js，请安装 Node.js 后重试。')
    started = []
    try:
        for name, port in SERVICES.items():
            pids = listeners(port)
            if pids:
                if stale(name):raise RuntimeError('检测到本项目代码／配置已更新或旧进程版本未知，请运行重启服务器命令。')
                record(name, pids[0])
                print(f'{name} 已运行，复用端口 {port}。', flush=True)
                continue
            args = [str(ROOT / '.venv/bin/python'), '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', str(port)] if name == 'backend' else [node, str(ROOT / 'node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', str(port), '--strictPort']
            with (RUNTIME / f'{name}.log').open('ab') as log:
                proc = subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,env=child_environment())
            started.append(proc)
            record(name, proc.pid)
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError(f'{name} 启动失败，请查看 .runtime/{name}.log。')
                if ready(port, name):
                    print(f'{name} 已启动：端口 {port}', flush=True)
                    break
                time.sleep(.3)
            else:
                raise RuntimeError(f'{name} 启动超时，请查看日志。')
        print('\nAnimatedScroll 已就绪：http://127.0.0.1:5173/', flush=True)
        if open_browser and sys.platform == 'darwin':
            subprocess.run(['/usr/bin/open', 'http://127.0.0.1:5173/'], check=False)
    except Exception:
        for proc in started:
            if proc.poll() is None:
                proc.terminate()
        raise


def stop():
    active=active_tasks()
    if active:print('正在停止本项目任务，已保存结果保留：'+ '、'.join(active))
    for name, port in SERVICES.items():
        pids = set(listeners(port))
        path = RUNTIME / f'{name}.json'
        if path.exists():
            try:
                pids.add(int(json.loads(path.read_text())['pid']))
            except (ValueError, KeyError, TypeError):
                pass
        owned = [pid for pid in pids if ours(pid, name)]
        for pid in owned:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 8
        while any(ours(pid, name) for pid in owned) and time.monotonic() < deadline:
            time.sleep(.2)
        remaining = [pid for pid in owned if ours(pid, name)]
        if remaining:
            print(f'{name} 正在结束任务，尚未退出；请稍后再双击关闭脚本。')
        else:
            path.unlink(missing_ok=True)
            print(f'{name} 已关闭。' if owned else f'{name} 未运行；其他程序保持不变。')


def status():
    print('项目：'+str(ROOT))
    for name,port in SERVICES.items():
        pids=listeners(port);owned=[pid for pid in pids if ours(pid,name)]
        print(f'{name} 端口{port}：'+('运行中'+('，代码或配置已更新，需要重启' if stale(name) else '，启动版本为当前版本') if owned else '被其他应用占用' if pids else '未运行'))
    values=child_environment();provider=values.get('MODEL_PROVIDER','aihubmix')
    key=values.get('DASHSCOPE_API_KEY' if provider=='dashscope' else 'AIHUBMIX_API_KEY')
    print('模型服务：'+provider+'；Key：'+('已配置' if key else '未配置'))
    tasks=active_tasks();print('运行任务：'+('、'.join(tasks) if tasks else '无'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start','stop','restart','status'])
    parser.add_argument('--no-browser',action='store_true')
    args = parser.parse_args()
    RUNTIME.mkdir(exist_ok=True)
    with (RUNTIME / 'control.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('另一项启动／关闭操作正在执行，请稍候。')
            return 1
        try:
            if args.action=='status':status()
            elif args.action=='start':start(not args.no_browser)
            elif args.action=='stop':stop()
            else:
                if active_tasks():raise RuntimeError('仍有运行任务，请先完成任务再重启；未中断现有任务。')
                stop();start(not args.no_browser)
            return 0
        except Exception as exc:
            print(f'操作失败：{exc}', file=sys.stderr)
            return 1


if __name__ == '__main__':
    sys.exit(main())
