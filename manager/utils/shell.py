"""subprocess 统一执行封装：参数数组、超时、日志、可读错误。"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from utils.log import get_logger


@dataclass
class CommandResult:
    cmd: List[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def brief(self) -> str:
        text = (self.stderr or self.stdout).strip()
        return text[-1200:] if text else f"exit code {self.returncode}"


def run(
    cmd: Sequence[str],
    cwd: Optional[os.PathLike] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: int = 600,
    quiet: bool = False,
    input_text: Optional[str] = None,
) -> CommandResult:
    args = [str(item) for item in cmd]
    log = get_logger()
    log.debug("run: " + " ".join(args))
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
        )
        result = CommandResult(args, proc.returncode, proc.stdout or "", proc.stderr or "")
    except FileNotFoundError:
        result = CommandResult(args, 127, "", f"command not found: {args[0]}")
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        result = CommandResult(args, 124, stdout, stderr + "\ncommand timed out")
    except PermissionError:
        result = CommandResult(args, 126, "", f"permission denied: {args[0]}")
    if result.returncode != 0:
        log.warn(f"exit {result.returncode}: {' '.join(args)} | {result.brief()}")
    elif not quiet:
        log.debug("ok: " + " ".join(args))
    return result


def run_ok(cmd: Sequence[str], **kwargs) -> bool:
    return run(cmd, quiet=True, **kwargs).ok


def output(cmd: Sequence[str], **kwargs) -> str:
    result = run(cmd, quiet=True, **kwargs)
    return result.stdout.strip() if result.ok else ""


def run_stream(cmd: Sequence[str], timeout: int = 3600, env: Optional[Dict[str, str]] = None) -> CommandResult:
    """流式执行长任务（如 brew install），逐行输出并写入日志。"""
    args = [str(item) for item in cmd]
    log = get_logger()
    log.info("stream: " + " ".join(args))
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    lines: List[str] = []
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=merged_env,
        )
    except (FileNotFoundError, PermissionError) as exc:
        return CommandResult(args, 127, "", str(exc))
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            lines.append(line)
            log.info(line)
            print(f"  {line}", flush=True)
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        lines.append("command timed out")
        return CommandResult(args, 124, "\n".join(lines), "timeout")
    return CommandResult(args, proc.returncode or 0, "\n".join(lines), "")


def which(name: str) -> Optional[str]:
    return shutil.which(name)
