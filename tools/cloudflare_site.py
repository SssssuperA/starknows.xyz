#!/usr/bin/env python3
"""Build, check, preview, authenticate and publish the free StarKnows static site."""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
from build_cloudflare_site import ROOT, DEFAULT_OUTPUT, TEMP_ROOT, build

VERSION = "4.152.0"
TOOLS = TEMP_ROOT / "starknows-cloudflare-tools"
ACCOUNT = "1652517d58bb53c544e3a9584765aa38"
SCOPES = [
    "account:read", "user:read", "workers:write",
    "workers_scripts:write", "workers_routes:write", "zone:read",
]


def cli():
    candidates = [
        TOOLS / "node-v22.23.4-darwin-arm64/bin/node",
        Path(shutil.which("node") or "/nonexistent"),
    ]
    for node in candidates:
        if not node.is_file():
            continue
        version = subprocess.check_output([str(node), "--version"], text=True).strip()
        if int(version.lstrip("v").split(".")[0]) < 22:
            continue
        installed = TOOLS / "packages/node_modules/wrangler/bin/wrangler.js"
        if installed.is_file():
            return [str(node), str(installed)], node.parent
        npx = node.parent / "npx"
        if npx.is_file():
            return [str(npx), "--yes", "wrangler@" + VERSION], node.parent
    raise RuntimeError("需要 Node.js 22 或更新版本；安装后重新运行本命令。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["build", "check", "preview", "login", "whoami", "deploy"])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", action="store_true", help="登录时使用官方设备授权流程")
    args = parser.parse_args()
    if args.action == "build":
        build(ROOT, args.output)
        return
    command, node_bin = cli()
    # Keep generated logs, CLI state and temporary credentials outside this project.
    # A restrictive umask prevents other local users from reading OAuth credentials.
    os.umask(0o077)
    TOOLS.mkdir(exist_ok=True)
    config_home = TOOLS / "config"
    config_home.mkdir(mode=0o700, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "PATH": str(node_bin) + os.pathsep + env.get("PATH", ""),
        "XDG_CONFIG_HOME": str(config_home),
        "WRANGLER_LOG_PATH": str(TOOLS / "logs") + "/",
        "WRANGLER_REGISTRY_PATH": str(TOOLS / "registry"),
        "WRANGLER_SEND_METRICS": "false",
        "CLOUDFLARE_ACCOUNT_ID": ACCOUNT,
    })
    if args.action == "login":
        options = ["login"] + (["--device"] if args.device else []) + ["--scopes", *SCOPES]
    elif args.action == "whoami":
        options = ["whoami"]
    else:
        # Always rebuild before preview or deployment, so an old successful build
        # cannot accidentally publish PDFs whose local contents have since changed.
        build(ROOT, args.output)
        config = str(args.output.resolve() / "wrangler.jsonc")
        if args.action == "preview":
            options = ["dev", "--config", config, "--local", "--ip", "127.0.0.1", "--port", "8787"]
        else:
            options = ["deploy", "--config", config]
            if args.action == "check":
                options.append("--dry-run")
    sys.stdout.flush()
    subprocess.run(command + options, cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print("Cloudflare 操作未完成：" + str(error), file=sys.stderr)
        sys.exit(1)
