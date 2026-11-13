"""Explicit opt-in elevated Windows logon task, with no stored credentials.

Never bypasses UAC on registration/removal. The task uses current-user
Interactive logon and Highest run level; no SYSTEM account or password.
"""
from __future__ import annotations
import base64
import ctypes
import ntpath
import os
from pathlib import Path
import subprocess
import sys

TASK_NAME = "FanARGBControl Elevated"


def ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def build_install_script(exe_path: str, mode: str) -> str:
    if mode not in {"gui", "agent"}:
        raise ValueError("Only gui and agent modes are valid")
    path = Path(exe_path)
    if not (path.is_absolute() or ntpath.isabs(exe_path)) or path.suffix.lower() != ".exe":
        raise ValueError("Autostart requires an absolute path to a packaged EXE")
    executable = ps_quote(str(path))
    name = ps_quote(TASK_NAME)
    argument = ps_quote("--headless" if mode == "agent" else "")
    return (
        "$ErrorActionPreference='Stop';"
        f"$p={executable};"
        "if (!(Test-Path -LiteralPath $p -PathType Leaf)) {throw 'EXE missing'};"
        "$user=[Security.Principal.WindowsIdentity]::GetCurrent().Name;"
        "$principal=New-ScheduledTaskPrincipal -UserId $user "
        "-LogonType Interactive -RunLevel Highest;"
        f"$action=New-ScheduledTaskAction -Execute $p -Argument {argument} "
        "-WorkingDirectory (Split-Path -Parent $p);"
        "$trigger=New-ScheduledTaskTrigger -AtLogOn -User $user;"
        "$settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries "
        "-DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Seconds 0) "
        "-MultipleInstances IgnoreNew -StartWhenAvailable;"
        f"Register-ScheduledTask -TaskName {name} -Action $action "
        "-Trigger $trigger -Principal $principal -Settings $settings -Force "
        "-ErrorAction Stop | Out-Null;"
    )


def build_remove_script() -> str:
    return (
        "$ErrorActionPreference='Stop';"
        f"$task=Get-ScheduledTask -TaskName {ps_quote(TASK_NAME)} "
        "-ErrorAction SilentlyContinue;"
        "if ($task) { Unregister-ScheduledTask -InputObject $task -Confirm:$false "
        "-ErrorAction Stop; }"
    )


def invoke_uac(script: str) -> None:
    """Ask Windows to elevate PowerShell; user must approve the UAC dialog.

    ShellExecute does not report script completion; the GUI must re-query the
    task status and must not claim that registration succeeded immediately.
    """
    if os.name != "nt":
        raise OSError("Windows Task Scheduler is only supported on Windows")
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    args = "-NoLogo -NoProfile -NonInteractive -EncodedCommand " + encoded
    rc = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", "powershell.exe", args, None, 1
    )
    if rc <= 32:
        raise OSError(f"UAC cancelled or PowerShell launch failed ({rc})")


def current_task() -> str:
    """Return a short status without reading passwords or task secrets."""
    if os.name != "nt":
        return "Недоступно (потрібен Windows)"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        ["schtasks.exe", "/Query", "/TN", TASK_NAME, "/FO", "LIST"],
        timeout=4.0, capture_output=True, text=True,
        errors="replace", creationflags=flags,
    )
    return "Налаштовано" if result.returncode == 0 else "Не налаштовано"


def packaged_executable() -> str:
    if not getattr(sys, "frozen", False):
        raise ValueError("Автозапуск доступний для встановленого FanARGBControl.exe")
    return str(Path(sys.executable).resolve())
