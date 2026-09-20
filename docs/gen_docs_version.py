"""Write docs/VERSION.md: badge + changelog from git tags. Usage: python docs/gen_docs_version.py"""
import pathlib
import re
import subprocess

R = pathlib.Path(__file__).resolve().parents[1]
v = re.search(r'__version__\s*=\s*"([^"]+)"', (R / "tube2note/__init__.py").read_text()).group(1)
tags = subprocess.check_output(["git", "tag", "--sort=-v:refname"], cwd=R, text=True).split()
url = subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=R, text=True).strip().removesuffix(".git")
L = [f"[![version v{v}](https://img.shields.io/badge/version-v{v}-blue)]({url}/releases/tag/v{v})", ""]
# ponytail: per-tag `git log` scans, fine for <100 tags; single-pass `git log --all` if slow
for i, t in enumerate(tags):
    rng = f"{tags[i + 1]}..{t}" if i + 1 < len(tags) else t
    log = subprocess.check_output(["git", "log", rng, "--oneline", "--no-decorate"], cwd=R, text=True).strip()
    cur = " (current)" if t.lstrip("v") == v else ""
    L += [f"## {t}{cur}", log or "(no changes)", ""]
(R / "docs/VERSION.md").write_text("\n".join(L))
print(L[0])
