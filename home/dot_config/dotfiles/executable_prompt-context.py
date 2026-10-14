#!/usr/bin/env python3
"""Render a native Starship module only inside a matching project. Read-only."""
import json
import os
import pathlib
import re
import stat
import sys

NODE_FILES = ("package.json", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", ".node-version", ".nvmrc")
LUA_FILES = (".lua-version", ".luarc.json", ".luarc.jsonc")
AWS_PACKAGES = ("aws-sdk", "aws-cdk-lib", "aws-amplify")


def read(path):
    try:
        info = path.stat()
        if stat.S_ISREG(info.st_mode) and info.st_size <= 1024 * 1024:
            with path.open(errors="replace") as source:
                value = source.read(1024 * 1024 + 1)
            return value if len(value) <= 1024 * 1024 else ""
    except OSError:
        pass
    return ""


def manifest(path):
    try:
        value = json.loads(read(path))
        return value if isinstance(value, dict) else {}
    except (ValueError, RecursionError):
        return {}


def aws_project(directory):
    if any((directory / name).is_file() for name in (".aws-project", "samconfig.toml", "cdk.json")) or (directory / "amplify").is_dir():
        return True
    package = manifest(directory / "package.json")
    for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        dependencies = package.get(section, {})
        if isinstance(dependencies, dict) and any(name in AWS_PACKAGES or name.startswith(("@aws-sdk/", "@aws-cdk/", "@aws-amplify/")) for name in dependencies):
            return True
    composer = manifest(directory / "composer.json")
    if any("aws/aws-sdk-php" in composer.get(section, {}) for section in ("require", "require-dev") if isinstance(composer.get(section, {}), dict)):
        return True
    for name in ("requirements.txt", "pyproject.toml", "go.mod"):
        text = "\n".join(line for line in read(directory / name).splitlines() if not line.lstrip().startswith(("#", "//")))
        if re.search(r"\b(?:boto3|botocore|aws-cdk-lib)\b|github\.com/aws/aws-sdk-go", text):
            return True
    serverless = manifest(directory / "serverless.json").get("provider", {})
    if serverless == "aws" or isinstance(serverless, dict) and serverless.get("name") == "aws":
        return True
    for name in ("serverless.yml", "serverless.yaml", "template.yml", "template.yaml"):
        text = read(directory / name)
        if re.search(r"(?m)^\s*(?:AWSTemplateFormatVersion:|Transform:\s*['\"]?AWS::|Type:\s*['\"]?AWS::)", text):
            return True
        provider_indent = None
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            if provider_indent is not None and indent <= provider_indent:
                provider_indent = None
            if re.fullmatch(r"\s*provider:\s*['\"]?aws['\"]?\s*(?:#.*)?", line):
                return True
            if re.fullmatch(r"\s*provider:\s*(?:#.*)?", line):
                provider_indent = indent
            elif provider_indent is not None and re.fullmatch(r"\s*name:\s*['\"]?aws['\"]?\s*(?:#.*)?", line):
                return True
    for index, path in enumerate(directory.glob("*.tf")):
        if index >= 64:
            break
        text = "\n".join(line for line in read(path).splitlines() if not line.lstrip().startswith(("#", "//")))
        if re.search(r'\bprovider\s+"aws"|\b(?:resource|data)\s+"aws_[^"]+"', text):
            return True
    return False


def project(module):
    home = pathlib.Path.home().resolve()
    directory = pathlib.Path.cwd()
    while directory != home and directory != directory.parent:
        if module == "nodejs" and (any((directory / name).is_file() for name in NODE_FILES) or (directory / "node_modules").is_dir()):
            return directory
        if module == "lua" and (any((directory / name).is_file() for name in LUA_FILES) or (directory / "lua").is_dir() or next(directory.glob("*.lua"), None) is not None):
            return directory
        if module == "aws" and aws_project(directory):
            return directory
        if (directory / ".git").exists():
            break
        directory = directory.parent
    return None


if __name__ == "__main__":
    module = sys.argv[1] if len(sys.argv) > 1 else ""
    if module not in ("nodejs", "lua", "aws"):
        sys.exit(2)
    root = project(module)
    if "--detect" in sys.argv:
        sys.exit(0 if root else 1)
    if root:
        os.execvp("starship", ["starship", "module", module, "--path", str(root)])
