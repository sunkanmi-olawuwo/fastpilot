#!/usr/bin/env python3
"""Publish wiki/*.md to the repo's GitHub Wiki (the separate .wiki.git repo).

The in-repo ``wiki/`` is canonical; this mirrors it to the GitHub Wiki for browsing.
Run after changing ``wiki/``:  ``uv run python scripts/publish_wiki.py``

Transforms applied so links resolve in the GitHub Wiki (which is flat):
  - ``[[index]]``        -> ``[[Home]]``           (index becomes the wiki Home page)
  - ``[[CLAUDE.md]]``    -> repo blob link         (it's a repo file, not a wiki page)
  - ``[[raw/README]]``   -> repo tree link         (raw/ holds the immutable contract)
  - ``[[plans/README]]`` -> repo tree link
Other ``[[page]]`` links map 1:1 to published pages and are left as-is. Mermaid blocks
(including ``[[ ]]`` subroutine nodes) are passed through untouched.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WIKI_DIR = Path(__file__).resolve().parent.parent / "wiki"
# Pages to publish (in sidebar order). index.md is rendered as Home.md.
ORDER = [
    "onboarding",
    "overview",
    "component-architecture",
    "endpoint-summary",
    "coding-conventions",
    "testing-strategy",
    "feature-coverage",
    "log",
]


def _slug() -> tuple[str, str]:
    url = subprocess.check_output(["git", "config", "--get", "remote.origin.url"], text=True).strip()
    m = re.search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?$", url)
    if not m:
        sys.exit(f"Could not parse owner/repo from remote: {url}")
    return m.group(1), m.group(2)


def _transform(text: str, owner: str, repo: str) -> str:
    blob = f"https://github.com/{owner}/{repo}/blob/main"
    tree = f"https://github.com/{owner}/{repo}/tree/main"
    text = text.replace("[[index]]", "[[Home]]")
    text = text.replace("[[CLAUDE.md]]", f"[CLAUDE.md]({blob}/CLAUDE.md)")
    text = text.replace("[[raw/README]]", f"[raw/ (immutable sources)]({tree}/wiki/raw)")
    text = text.replace("[[plans/README]]", f"[plans/]({tree}/wiki/plans)")
    return text


def _sidebar(owner: str, repo: str) -> str:
    titles = {
        "onboarding": "Onboarding",
        "overview": "Overview",
        "component-architecture": "Component Architecture",
        "endpoint-summary": "Endpoint Summary",
        "coding-conventions": "Coding Conventions",
        "testing-strategy": "Testing Strategy",
        "feature-coverage": "Feature Coverage",
        "log": "Change Log",
    }
    lines = ["### FastPilot Wiki", "", "- [[Home]]"]
    lines += [f"- [[{titles[p]}|{p}]]" for p in ORDER]
    lines += ["", f"[↩ Repository](https://github.com/{owner}/{repo})"]
    return "\n".join(lines) + "\n"


def main() -> None:
    owner, repo = _slug()
    wiki_url = f"https://github.com/{owner}/{repo}.wiki.git"
    tmp = Path(tempfile.mkdtemp(prefix="fastpilot-wiki-"))
    work = tmp / "wiki"

    # Clone the wiki repo; if it isn't initialized yet, bootstrap a fresh one.
    cloned = subprocess.run(["git", "clone", wiki_url, str(work)], capture_output=True, text=True).returncode == 0
    if not cloned:
        print("Wiki repo not initialized — bootstrapping a fresh one.")
        work.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(work)], check=True)
        subprocess.run(["git", "-C", str(work), "remote", "add", "origin", wiki_url], check=True)
    else:
        for f in work.glob("*.md"):  # clean slate so deletions propagate
            f.unlink()

    # Home page from index.md; content pages mirrored with transformed links.
    (work / "Home.md").write_text(_transform((WIKI_DIR / "index.md").read_text(), owner, repo))
    for page in ORDER:
        (work / f"{page}.md").write_text(_transform((WIKI_DIR / f"{page}.md").read_text(), owner, repo))
    (work / "_Sidebar.md").write_text(_sidebar(owner, repo))

    subprocess.run(["git", "-C", str(work), "add", "-A"], check=True)
    diff = subprocess.run(["git", "-C", str(work), "diff", "--cached", "--quiet"]).returncode
    if diff == 0:
        print("Wiki already up to date — nothing to publish.")
        shutil.rmtree(tmp, ignore_errors=True)
        return
    subprocess.run(["git", "-C", str(work), "commit", "-q", "-m", "Publish wiki from repo wiki/"], check=True)
    branch = "master" if not cloned else subprocess.check_output(
        ["git", "-C", str(work), "rev-parse", "--abbrev-ref", "HEAD"], text=True
    ).strip()
    subprocess.run(["git", "-C", str(work), "push", "-q", "origin", f"HEAD:{branch}"], check=True)
    print(f"Published {len(ORDER) + 1} pages to {wiki_url} ({branch}).")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
