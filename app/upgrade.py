"""一键升级：用升级包里的新版本替换已安装的程序，数据目录保持不动。

用法（普通用户双击 升级程序.exe 即可）：
    升级程序.exe

开发/自测：
    升级程序.exe --package 升级包目录 --target 现有程序目录 --yes --no-launch
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

APP_TITLE = "质量节点升级"
DEFAULT_EXE = "质量节点.exe"
BUILD_DIR_NAME = "新版本"
DATA_DIR_NAME = "质量节点"


def data_dir() -> Path:
    custom = os.environ.get("QUALITY_DATA_DIR")
    if custom:
        return Path(custom).expanduser()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / DATA_DIR_NAME
    return Path.home() / ".local" / "share" / DATA_DIR_NAME


def text_dialog(message, title=APP_TITLE, error=False):
    """尽量用系统对话框提示；没有图形库时退回控制台。"""
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        if error:
            messagebox.showerror(title, message, parent=root)
        else:
            messagebox.showinfo(title, message, parent=root)
        root.destroy()
        return
    except Exception:
        print(message, file=sys.stderr if error else sys.stdout, flush=True)


def ask_yes_no(message, title=APP_TITLE) -> bool:
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        answer = messagebox.askyesno(title, message, parent=root)
        root.destroy()
        return bool(answer)
    except Exception:
        return True


def ask_folder(initial=None) -> Path | None:
    try:
        import tkinter
        from tkinter import filedialog

        root = tkinter.Tk()
        root.withdraw()
        chosen = filedialog.askdirectory(
            title="请选择当前正在使用的“质量节点”文件夹（里面应有 质量节点.exe）",
            initialdir=initial or str(Path.home()),
            mustexist=True,
        )
        root.destroy()
        return Path(chosen) if chosen else None
    except Exception:
        return None


def read_manifest(package: Path) -> dict:
    manifest_path = package / "upgrade.json"
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def find_target(explicit=None) -> Path | None:
    if explicit:
        return Path(explicit)
    install_file = data_dir() / "install.txt"
    if install_file.is_file():
        try:
            exe = install_file.read_text(encoding="utf-8").strip()
        except Exception:
            exe = ""
        if exe and Path(exe).is_file():
            return Path(exe).parent
    return None


def stop_running(exe_name: str):
    """关闭正在运行的程序；关不掉就交给后面的重试与提示处理。"""
    stem = Path(exe_name).stem
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/IM", exe_name, "/F"], capture_output=True, timeout=20)
        else:
            subprocess.run(["pkill", "-f", stem], capture_output=True, timeout=10)
    except Exception:
        pass
    time.sleep(0.6)


def is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def swap_folder(target: Path, build: Path, exe_name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = target.with_name(f"{target.name}-旧-{stamp}")
    last_error = None
    for _ in range(20):
        try:
            target.rename(backup)
            last_error = None
            break
        except OSError as exc:  # 文件被占用时稍等再试
            last_error = exc
            time.sleep(0.5)
    if last_error is not None:
        raise RuntimeError(f"程序文件夹无法改名，可能还在运行或被占用：{last_error}")
    try:
        shutil.copytree(build, target)
        if not (target / exe_name).is_file():
            raise RuntimeError("复制完成后没有找到程序文件，升级包可能不完整。")
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        try:
            backup.rename(target)
        except Exception:
            pass
        raise
    return backup


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="质量节点一键升级")
    parser.add_argument("--package", help="升级包所在目录（默认是程序自己所在目录）")
    parser.add_argument("--target", help="现有程序目录（默认从数据目录的 install.txt 读取）")
    parser.add_argument("--yes", action="store_true", help="不弹确认框，直接升级")
    parser.add_argument("--no-launch", action="store_true", help="升级后不自动启动程序")
    args = parser.parse_args(argv)

    package = Path(args.package) if args.package else Path(sys.executable).parent
    manifest = read_manifest(package)
    exe_name = manifest.get("exe") or DEFAULT_EXE
    build = package / BUILD_DIR_NAME / manifest.get("folder", DATA_DIR_NAME)

    if not (build / exe_name).is_file():
        text_dialog(
            f"升级包不完整：没有找到 {BUILD_DIR_NAME}\\{build.name}\\{exe_name}。\n"
            "请重新解压整个升级包后再试。",
            error=True,
        )
        return 1

    target = find_target(args.target)
    if target is None:
        target = ask_folder()
    if target is None:
        text_dialog("没有找到现有程序的位置，升级已取消。", error=True)
        return 1
    target_exe = target / exe_name
    if not target_exe.is_file():
        candidates = [p for p in target.glob("*.exe") if p.is_file()] if target.is_dir() else []
        if not candidates:
            text_dialog(f"所选文件夹里没有找到程序：\n{target}", error=True)
            return 1
        target_exe = candidates[0]
        exe_name = target_exe.name

    if is_inside(build, target):
        text_dialog(
            "升级包放在了要替换的程序文件夹里面。\n"
            "请把升级包解压到桌面、D 盘或 U 盘等别的目录，再双击升级程序。",
            error=True,
        )
        return 1

    version = manifest.get("version", "")
    if not args.yes and not ask_yes_no(
        "将把当前程序替换为新版本"
        + (f"（{version}）" if version else "")
        + f"。\n\n当前程序：{target}\n"
        + f"替换前会先把旧程序备份成旁边的“{target.name}-旧-时间”，\n"
        + "项目组与检查记录保存在本机另一个位置，不会受影响。\n\n继续吗？"
    ):
        return 0

    stop_running(exe_name)
    try:
        backup = swap_folder(target, build, exe_name)
    except Exception as exc:
        text_dialog(f"升级没有完成，已尝试恢复原来的版本。\n\n原因：{exc}", error=True)
        return 1

    if not args.no_launch:
        try:
            os.startfile(str(target / exe_name)) if os.name == "nt" else subprocess.Popen([str(target / exe_name)])
        except Exception as exc:
            text_dialog(f"新版本已替换，但自动启动失败，请手动双击程序。\n\n{exc}", error=True)
            return 1
    text_dialog(
        "升级完成，程序已重新打开。\n\n"
        f"旧版本保留在：\n{backup}\n"
        "确认新版本里的项目组与记录都正常后，这个旧文件夹可以删掉。"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # 保证双击运行时也能看到错误
        text_dialog(f"升级程序出错：{exc}", error=True)
        sys.exit(1)
