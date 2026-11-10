#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows local entry point, sharing preflight, process control and history.

Usage: python scripts/run_local.py jobs/example.env [--no-render] [--project DIR]
Exit codes: engine nonzero is preserved; 2 is configuration/preflight failure,
3 is a completed process without verified business success, 130 is cancellation.
"""

import argparse
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'platform/backend'))
sys.path.insert(0, str(ROOT / 'scripts'))

import core  # noqa: E402
from file_safety import FileTransaction  # noqa: E402
from project_config import load_local  # noqa: E402
from render_schema import build_table, read_env_file  # noqa: E402


CONFIGURATION_FAILURE = 2
BUSINESS_FAILURE = 3


class RenderFailed(ValueError):
    def __init__(self, code):
        self.exit_code = code if isinstance(code, int) and code else CONFIGURATION_FAILURE
        super().__init__('本次生成失败，已保留上一次完整运行配置，未启动引擎')


def wait_for_run(sid, cancel=False):
    """Drain bounded log pages and wait through cancellation and archiving."""
    cursor = 0
    cancelled = cancel
    stop_pending = cancel
    while True:
        try:
            if stop_pending:
                try:
                    core.RUNNER.stop(sid)
                    stop_pending = False
                except (OSError, RuntimeError) as exc:
                    print(f'[重试] 停止尚未完成：{exc}', flush=True)
                    time.sleep(.1)
                    continue
            report = core.RUNNER.output(sid, cursor, limit=500)
            if report.get('error'):
                raise ValueError(report['error'])
            lines = report.get('lines', [])
            for line in lines:
                print(line, flush=True)
            cursor = report.get('next_since', report.get('next', cursor + len(lines)))
            # A done process can still have more archived log pages to print.
            if report.get('status') == 'done' and cursor >= report.get('total', cursor):
                break
            time.sleep(.1)
        except KeyboardInterrupt:
            if not cancelled:
                cancelled = True
                print('\n[取消] 正在停止进程树并保存运行记录，请稍候……', flush=True)
            else:
                print('[等待] 进程树退出和运行记录保存完成后返回。', flush=True)
            stop_pending = True
    result = report.get('result') or {}
    verdict = result.get('verdict', 'unconfirmed')
    names = {'success': '验证成功', 'failed': '验证失败', 'unconfirmed': '结果未确认',
             'cancelled': '已取消', 'stale': '当前产物已变化'}
    print(f'\n[结果] {names.get(verdict, "结果未确认")}；进程退出码 {report.get("exit")}', flush=True)
    if report.get('internal_error'):
        print('[注意] ' + report['internal_error'], flush=True)
    if report.get('history_id'):
        print(f'[记录] {report["history_id"]}', flush=True)
    archive = report.get('archive') or {}
    if archive.get('dir'):
        print(f'[归档] {archive["dir"]}', flush=True)
    if archive.get('status') and archive['status'] != 'complete':
        print('[注意] 归档不完整，请查看最近运行中的归档说明；当时的验证结论与归档完整性分别记录。', flush=True)
    if cancelled or report.get('cancelled') or verdict == 'cancelled':
        return 130
    code = report.get('exit')
    if isinstance(code, int) and code:
        return code
    return 0 if code == 0 and verdict == 'success' else BUSINESS_FAILURE


def run(args):
    job_path = Path(args.job)
    if not job_path.is_absolute():
        job_path = ROOT / job_path
    env = dict(load_local(core.ENV_FILE, project=args.project))
    context_token = core.PROJECT_CONTEXT.set(env)
    sid = None
    try:
        job = read_env_file(str(job_path), '任务单')
        table = build_table(env, job)
        schemas = [item.strip() for item in table.get('SCHEMA_NAME', '').split(',') if item.strip()]
        if len(schemas) != 1:
            raise ValueError('本地受管运行要求每个任务单指定一个 XML，请为多个运行单分别创建任务单后逐个运行')
        context = {'project': env['PROJECT_DIR'], 'bin_dir': table['EXE_DIR'], 'operation': 'run'}
        with core.RUNTIME.operation('本地运行', context) as token:
            # Render modifies shared runtime files before start_lishuttle runs.
            core.RUNTIME.acquire_resources(token, context)
            if args.no_render or table.get('RENDER_BEFORE_RUN', '1') == '0':
                print('[跳过] 沿用已有运行单，仍执行完整运行前检查。', flush=True)
            else:
                print('[生成] 正在生成运行单……', flush=True)
                with FileTransaction() as transaction:
                    rendered = core.run_render(str(job_path), transaction=transaction)
                    if rendered.get('output'):
                        print(rendered['output'], flush=True)
                    if not rendered.get('generated') or rendered.get('status') not in ('ready', 'missing_inputs'):
                        raise RenderFailed(rendered.get('exit_code'))
            print('[检查] 正在执行运行前检查……', flush=True)
            sid, message = core.start_lishuttle(schemas[0], table['FUNC'], table.get('TASK_ID') or '0')
            if sid is None:
                raise ValueError(message)
        print(f'[运行] 会话 {sid}；按 Ctrl+C 取消并保存记录。', flush=True)
        return wait_for_run(sid)
    except KeyboardInterrupt:
        if sid is None:
            raise
        return wait_for_run(sid, cancel=True)
    finally:
        try:
            # Also covers interruption between start returning and log polling,
            # and terminal write failures while a process is still running.
            while True:
                try:
                    core.RUNNER.shutdown()
                    break
                except KeyboardInterrupt:
                    print('[等待] 正在停止进程树并完成运行记录。', flush=True)
        finally:
            core.PROJECT_CONTEXT.reset(context_token)


def main(argv=None):
    parser = argparse.ArgumentParser(description='本地受管运行：预检、进程树控制、结果验证与历史归档')
    parser.add_argument('job', help='任务单 .env 路径')
    parser.add_argument('--no-render', action='store_true', help='沿用已有 XML，仍执行运行前检查')
    parser.add_argument('--project', help='本地项目目录')
    args = parser.parse_args(argv)
    try:
        return run(args)
    except RenderFailed as exc:
        print('[错误] ' + str(exc), flush=True)
        return exc.exit_code
    except KeyboardInterrupt:
        print('\n[取消] 已停止本地运行准备。', flush=True)
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print('[错误] ' + str(exc), flush=True)
        return CONFIGURATION_FAILURE
    except SystemExit as exc:
        # Existing job/template readers use SystemExit for invalid input.
        if isinstance(exc.code, int):
            return exc.code or CONFIGURATION_FAILURE
        print('[错误] ' + str(exc.code), flush=True)
        return CONFIGURATION_FAILURE


if __name__ == '__main__':
    sys.exit(main())
