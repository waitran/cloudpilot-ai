#!/usr/bin/env python3
"""Check the stage-0 repository offline using only Python's standard library."""

import ast
import configparser
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DIRS = (
    "backend", "frontend", "infrastructure/docker", "infrastructure/kubernetes",
    "infrastructure/monitoring", "tests", "scripts", "docs/architecture",
    "docs/development", "docs/decisions", ".github/workflows",
)
REQUIRED_FILES = (
    "README.md", "CONTRIBUTING.md", ".env.example", ".gitignore", ".editorconfig",
    ".python-version", ".nvmrc", ".prettierrc.json", "ruff.toml", "Makefile",
    ".github/workflows/ci.yml", "docs/architecture/overview.md",
    "docs/architecture/components.md", "docs/architecture/security.md",
    "docs/development/setup.md", "docs/development/roadmap.md",
    "docs/development/quality.md", "docs/development/stage-0-report.md",
    "docs/decisions/0001-modular-monolith.md",
)
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{50,}\b"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "credential URL": re.compile(r"[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@", re.I),
    "assigned secret": re.compile(
        r"(?im)^[ \t]*(?:[A-Z_]*(?:API_KEY|TOKEN|PASSWORD|SECRET))[ \t]*=[ \t]*[^\s#\"']+"
    ),
}
LOCAL_LINK = re.compile(r"!?\[[^\]\n]*\]\(([^\s)]+)\)")


def git(*args: str, input_bytes: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args], input=input_bytes, capture_output=True, check=False
    )
    if result.returncode:
        raise RuntimeError(f"git {args[0]} failed (exit {result.returncode})")
    return result.stdout


def unsafe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        any(part in {".aws", ".kube", "secrets", ".venv", "node_modules"} for part in path.parts)
        or (path.name.startswith(".env") and path.name != ".env.example")
        or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".tfvars", ".tfstate"}
        or ".tfstate." in path.name
        or path.name.startswith(("id_rsa", "id_ed25519", "service-account"))
        or path.name == "credentials.json"
    )


def check_text(name: str, raw: bytes, label: str, errors: list[str]) -> None:
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        errors.append(f"{label}: expected UTF-8 text; binary files require explicit review")
        return
    if b"\r" in raw or (raw and not raw.endswith(b"\n")):
        errors.append(f"{label}: use LF and a final newline")
    if any(line.rstrip(" \t") != line for line in content.splitlines()):
        errors.append(f"{label}: trailing whitespace")
    for kind, pattern in SECRET_PATTERNS.items():
        if pattern.search(content):
            errors.append(f"{label}: possible {kind} (value redacted)")
    try:
        if name.endswith(".json"):
            json.loads(content)
        elif name.endswith(".toml"):
            tomllib.loads(content)
        elif name.endswith(".py"):
            ast.parse(content, filename=name)
    except (ValueError, SyntaxError) as error:
        errors.append(f"{label}: invalid syntax ({type(error).__name__})")
    if name.endswith(".md"):
        if sum(line.startswith("```") for line in content.splitlines()) % 2:
            errors.append(f"{label}: unclosed code fence")
        for match in LOCAL_LINK.finditer(content):
            target = urlsplit(match.group(1))
            if target.scheme or target.netloc or not target.path:
                continue
            resolved = (ROOT / name).parent.joinpath(unquote(target.path)).resolve()
            if not resolved.is_relative_to(ROOT) or not resolved.exists():
                errors.append(f"{label}: missing or out-of-repository Markdown link")


def check_ignore(errors: list[str]) -> None:
    protected = (
        ".env", ".env.production", "backend/.env", "local.pem", "local.key",
        ".venv/bin/python", "frontend/node_modules/package/index.js",
        "infrastructure/live.tfstate", "infrastructure/local.tfvars", ".kube/config",
        ".aws/credentials", "secrets/local.json", "credentials.json",
    )
    result = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "--no-index", "--stdin", "-z"],
        input="\0".join(protected).encode() + b"\0", capture_output=True, check=False,
    )
    if result.returncode not in {0, 1}:
        errors.append("git check-ignore failed")
        return
    ignored = set(result.stdout.decode().split("\0"))
    for name in protected:
        if name not in ignored:
            errors.append(f".gitignore: missing protection for {name}")
    example = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "--no-index", ".env.example"],
        capture_output=True, check=False,
    )
    if example.returncode != 1:
        errors.append(".env.example must not be ignored")


def main() -> int:
    errors: list[str] = []
    for name in REQUIRED_DIRS:
        if not (ROOT / name).is_dir():
            errors.append(f"missing directory: {name}")
    for name in REQUIRED_FILES:
        if not (ROOT / name).is_file():
            errors.append(f"missing file: {name}")
    try:
        toplevel = Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve()
        if toplevel != ROOT:
            errors.append("project must have an independent Git repository")
        names = sorted(set(
            git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
            .decode().strip("\0").split("\0")
        ) - {""})
        if not names:
            errors.append("no repository files found")
        for name in names:
            path = ROOT / name
            if unsafe_name(name):
                errors.append(f"forbidden repository path: {name}")
            elif path.is_symlink():
                errors.append(f"symlink requires explicit review: {name}")
            elif path.is_file():
                check_text(name, path.read_bytes(), name, errors)
            else:
                errors.append(f"missing tracked file: {name}")
        # Inspect the actual index even when the worktree has already been sanitized.
        entries = git("ls-files", "--stage", "-z").decode().strip("\0").split("\0")
        for entry in filter(None, entries):
            metadata, name = entry.split("\t", 1)
            mode, blob, stage = metadata.split()
            if stage != "0":
                errors.append(f"unmerged index entry: {name}")
            elif unsafe_name(name) or mode not in {"100644", "100755"}:
                errors.append(f"forbidden staged path or file mode: {name}")
            else:
                check_text(name, git("cat-file", "blob", blob), f"index:{name}", errors)
        check_ignore(errors)
    except (OSError, RuntimeError, ValueError) as error:
        errors.append(f"repository inspection failed ({type(error).__name__}): {error}")
    try:
        editor = configparser.ConfigParser(interpolation=None)
        editor.read_string("[root]\n" + (ROOT / ".editorconfig").read_text())
        if editor["root"]["root"] != "true":
            errors.append(".editorconfig must declare root = true")
        if (ROOT / ".python-version").read_text().strip() != "3.12":
            errors.append("stage-0 Python target must be 3.12")
        if (ROOT / ".nvmrc").read_text().strip() != "24":
            errors.append("planned Node.js target must be 24 LTS")
    except (OSError, KeyError, configparser.Error) as error:
        errors.append(f"invalid repository configuration ({type(error).__name__})")
    if errors:
        for error in sorted(set(errors)):
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS: structure, configuration, links, syntax and secret checks ({len(names)} files)")
    print("Secret checks are heuristic. No remote CI or application tests are implied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
