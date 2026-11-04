"""旁路构建候选包并核对内容身份；不启动托盘、桥接或游戏。

用法：
  python tools/build_candidate.py --base <基线包目录> --out <新输出目录> --allow <改动文件>...
  python tools/build_candidate.py --base ... --out ... --allow ... --verify-only

`--allow` 列出本次允许变化的源文件（相对仓库根）。其余字节码必须与基线包完全一致；
已允许的模块必须与当前源码编译出的字节码一致；桥接与托盘两个 exe 的内容身份都记进
`<out>/package-check.json`，包内全部分发文件的 sha256 记进 `<out>/package-hash.json`。
任何一项不符就以非零码退出，且不写启用标记。
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader, PKG_ITEM_PYZ

BRIDGE_EXE = "WolverineDS5-bridge.exe"
APP_EXE = "WolverineDS5.exe"
APP_MODULES = ("app", "app.core", "app.window", "app.bridge", "app.native", "app.synapse",
               "app.ui_model", "app.qml_window", "settings")
DEFAULT_TESTS = ("test_sensa_multiband.py", "test_pc_bridge.py", "test_sensa_frame.py", "test_settings.py",
                 "app/test_core.py")
# 这些文件随包分发或决定构建输入，必须与源码一致；不参与字节码比对。
# QML 是运行时从 _internal/ui 读的松散文件，不加进这里界面改动就会静默漏过校验。
ASSET_FILES = ("sensa-device.json", "WolverineDS5.spec", "wolverine-capture.exe", "SDL3.dll",
               "ui/StatusPage.qml")
VENDOR_HINTS = ("HAR.dll", "Interhaptics", "RazerProvider")
MANIFEST_NAME = "package-hash.json"
# 发布清单只收分发文件：清单自身、内容身份核对结果、字节码缓存与日志都不参与。
MANIFEST_SKIP_FILES = (MANIFEST_NAME, "package-check.json")
MANIFEST_SKIP_SUFFIXES = (".pyc", ".log")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def archive_modules(path):
    archive = CArchiveReader(str(path))
    name = next(key for key, entry in archive.toc.items() if entry[-1] == PKG_ITEM_PYZ)
    return archive.open_embedded_archive(name)


def module_path(source, name):
    path = source / name.replace(".", "/")
    # 包（如 app，版本号在它的 __init__.py）对应目录下的 __init__.py。
    return path / "__init__.py" if path.is_dir() else path.with_suffix(".py")


def compiled(source, name, code):
    path = module_path(source, name)
    if not path.exists():
        # 第三方包没有仓库源码可比对，只要它能被加载即可。
        return True
    return code == compile(path.read_text(encoding="utf-8"), code.co_filename, "exec",
                           dont_inherit=True)


def frozen_assets(source):
    assets = {}
    for path in list(source.glob("*.py")) + list((source / "app").glob("*.py")):
        assets[str(path.relative_to(source))] = digest(path)
    for name in ASSET_FILES:
        path = source / name
        if path.exists():
            assets[name] = digest(path)
    return assets


def report(package, baseline, source, allow, assets, marker, allowed_assets=()):
    bridge, old_bridge = archive_modules(package / BRIDGE_EXE), archive_modules(baseline / BRIDGE_EXE)
    app, old_app = archive_modules(package / APP_EXE), archive_modules(baseline / APP_EXE)
    changed, unchanged, missing = {}, {}, []
    for name in old_bridge.toc:
        if name not in bridge.toc:
            missing.append(name)
            continue
        if name in allow:
            changed[name] = compiled(source, name, bridge.extract(name))
        else:
            unchanged[name] = bridge.extract(name) == old_bridge.extract(name)
    for name in bridge.toc:
        if name not in old_bridge.toc:
            changed[name] = compiled(source, name, bridge.extract(name))
    app_changed, app_unchanged = {}, {}
    for name in APP_MODULES:
        if name in allow:
            app_changed[name] = compiled(source, name, app.extract(name))
        else:
            app_unchanged[name] = app.extract(name) == old_app.extract(name)
    if "app.main" in allow:  # 入口模块随托盘源码变化，允许时不再与基线比对
        app_changed["entry_main"] = True
    else:
        app_unchanged["entry_main"] = (CArchiveReader(str(package / APP_EXE)).extract("main")
                                       == CArchiveReader(str(baseline / APP_EXE)).extract("main"))
    vendor = [str(path.relative_to(package)) for path in package.rglob("*.dll")
              if any(hint in path.name for hint in VENDOR_HINTS)]
    assets_unchanged = {}
    for name in ASSET_FILES:
        new_path, old_path = package / "_internal" / name, baseline / "_internal" / name
        # 归档里的二进制（capture / SDL3）不入库，只能与基线包比对；仓库内文件与源码比对。
        # --allow-asset 显式放行的二进制仍要求包内副本与仓库文件一致。
        if name in allowed_assets and new_path.exists() and (source / name).exists():
            assets_unchanged[name] = digest(new_path) == digest(source / name)
        elif new_path.exists() and old_path.exists():
            assets_unchanged[name] = digest(new_path) == digest(old_path)
        elif new_path.exists() and (source / name).exists():
            assets_unchanged[name] = digest(new_path) == digest(source / name)
    result = {"changed_modules_match_source": changed,
              "other_bridge_modules_unchanged": unchanged,
              "missing_from_new_build": missing,
              "changed_app_modules_match_source": app_changed,
              "unchanged_app_modules": app_unchanged,
              "source_unchanged_during_build": all(digest(source / name) == sha for name, sha in assets.items()),
              "assets_unchanged": assets_unchanged,
              "allowed_assets": sorted(allowed_assets),
              "bundled_vendor_dlls": vendor,
              "source_sha256": assets,
              "executables_sha256": {name: digest(package / name) for name in (APP_EXE, BRIDGE_EXE)}}
    result["passed"] = (not missing and all(changed.values()) and all(unchanged.values())
                        and all(app_changed.values()) and all(app_unchanged.values())
                        and result["source_unchanged_during_build"] and all(result["assets_unchanged"].values())
                        and not vendor)
    if result["passed"] and marker:
        (package / "_internal" / marker).parent.mkdir(parents=True, exist_ok=True)
        (package / "_internal" / marker).write_text("enabled\n", encoding="utf-8")
    return result


def candidate_version(source, output):
    """版本取候选目录名（candidate-1.1.45）；目录名不带版本时回落到源码 app/__init__.py。"""
    if output.name.startswith("candidate-"):
        return output.name[len("candidate-"):]
    init = source / "app" / "__init__.py"
    found = re.search(r'__version__\s*=\s*"([^"]+)"', init.read_text(encoding="utf-8"))
    return found.group(1) if found else "unknown"


def write_manifest(root, version):
    """生成发布包哈希清单；键是相对运行时根目录（onedir 的 _internal）的路径。

    运行时的 check_integrity 用 core.root_dir()（打包后即 _MEIPASS）拼路径，
    所以清单必须放在 _internal 里、键也相对它，否则自检读不到。
    """
    files, total = {}, 0
    for path in root.rglob("*"):
        if not path.is_file() or path.name in MANIFEST_SKIP_FILES:
            continue
        if path.suffix in MANIFEST_SKIP_SUFFIXES or "__pycache__" in path.parts:
            continue
        files[path.relative_to(root).as_posix()] = digest(path)
        total += path.stat().st_size
    files = dict(sorted(files.items()))
    canonical = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    data = {"version": version,
            "created": datetime.now().astimezone().isoformat(timespec="seconds"),
            "files": files,
            "count": len(files),
            "total_bytes": total,
            "manifest_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}
    (root / MANIFEST_NAME).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    return data


def verify_manifest(root, data):
    """回读清单，确认落盘内容可解析且 manifest_sha256 与 files 一致。"""
    try:
        written = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    files = written.get("files", {})
    canonical = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (written.get("version") == data["version"] and written.get("count") == len(files)
            and written.get("manifest_sha256") == hashlib.sha256(canonical.encode("utf-8")).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--base", required=True, help="用于比对的基线包目录（含 WolverineDS5/）")
    parser.add_argument("--out", required=True, help="本次候选输出目录（不存在时新建）")
    parser.add_argument("--allow", nargs="+", default=[], help="允许变化的源文件，相对仓库根")
    parser.add_argument("--marker", default="", help="构建通过后写入 _internal 的标记文件名")
    parser.add_argument("--allow-asset", nargs="*", default=[], help="允许相对基线变化的包内二进制；仍需与仓库文件一致")
    parser.add_argument("--spec", default="WolverineDS5.spec")
    parser.add_argument("--tests", nargs="*", default=list(DEFAULT_TESTS))
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    source, baseline, output = Path(args.source).resolve(), Path(args.base).resolve(), Path(args.out).resolve()
    allow = {name.removesuffix(".py").replace("\\", ".").replace("/", ".").removesuffix(".__init__")
             for name in args.allow}
    assets = frozen_assets(source) if args.verify_only is False else None
    if not args.verify_only and output.exists():
        raise SystemExit(f"{output} 已存在，拒绝覆盖")
    if not args.verify_only:
        subprocess.run(["git", "diff", "--check"], cwd=source, check=True)
        test = subprocess.run([sys.executable, "-X", "utf8", "-m", "pytest", *args.tests, "-q",
                               "-p", "no:cacheprovider"], cwd=source, capture_output=True, text=True,
                              encoding="utf-8")
        print(test.stdout.strip().splitlines()[-1] if test.stdout.strip() else test.stderr)
        if test.returncode:
            raise SystemExit("回归测试未通过")
        assets = frozen_assets(source)
        output.mkdir(parents=True)
        log = output.parent / (output.name + "-build.log")
        with log.open("w", encoding="utf-8") as handle:
            build = subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(output),
                                    "--workpath", str(output.parent / (".build-" + output.name)), args.spec],
                                   cwd=source, stdout=handle, stderr=subprocess.STDOUT)
        if build.returncode:
            raise SystemExit(f"构建失败，详见 {log}")
    else:
        assets = frozen_assets(source)
    result = report(output / "WolverineDS5", baseline / "WolverineDS5", source, allow, assets, args.marker,
                    args.allow_asset)
    app_root = output / "WolverineDS5" / "_internal"
    manifest = write_manifest(app_root, candidate_version(source, output))
    result["manifest"] = verify_manifest(app_root, manifest)
    if not result["manifest"]:
        print(f"{app_root / MANIFEST_NAME} 回读校验失败，发布清单不可信", file=sys.stderr)
    (output / "package-check.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "source_sha256"}, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
