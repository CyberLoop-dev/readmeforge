#!/usr/bin/env python3
"""readmeforge: generate a polished README.md and an animated SVG banner.

Pure standard library. Run `readmeforge --help` for usage.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

try:  # Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None

__version__ = "0.1.0"

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    "target", ".tox", ".mypy_cache", ".idea", ".vscode",
}
LANGS = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin",
    ".rb": "Ruby", ".php": "PHP", ".c": "C", ".cpp": "C++", ".cs": "C#",
    ".swift": "Swift", ".sh": "Shell", ".html": "HTML", ".css": "CSS",
}
THEMES = {
    "green": ("#3fb950", "#2dd4bf"),
    "purple": ("#a371f7", "#f778ba"),
    "blue": ("#58a6ff", "#79c0ff"),
    "orange": ("#ff9a3c", "#ff5e62"),
}
LICENSE_SIGNATURES = [
    ("MIT License", "MIT"),
    ("Apache License", "Apache-2.0"),
    ("GNU GENERAL PUBLIC LICENSE", "GPL"),
    ("GNU LESSER GENERAL PUBLIC LICENSE", "LGPL"),
    ("Mozilla Public License", "MPL-2.0"),
    ("BSD", "BSD"),
    ("free and unencumbered software", "Unlicense"),
]


@dataclass
class Project:
    name: str
    description: str = ""
    version: str = ""
    ecosystem: str = ""
    languages: list = field(default_factory=list)
    license: str = ""
    has_tests: bool = False
    workflow: str = ""
    repo_url: str = ""
    commands: list = field(default_factory=list)
    main_file: str = ""
    tree: str = ""


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def list_files(root: Path) -> list[str]:
    found = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts) or not path.is_file():
            continue
        found.append(rel.as_posix())
    return sorted(found)


def _regex_field(text: str, key: str) -> str:
    match = re.search(rf'^\s*{key}\s*=\s*["\']([^"\']*)["\']', text, re.M)
    return match.group(1) if match else ""


def parse_pyproject(text: str) -> dict:
    if tomllib:
        try:
            data = tomllib.loads(text)
        except Exception:
            data = {}
        proj = data.get("project", {})
        return {
            "name": proj.get("name", ""),
            "description": proj.get("description", ""),
            "version": proj.get("version", ""),
            "commands": list(proj.get("scripts", {}).keys()),
        }
    commands = []
    section = re.search(r"\[project\.scripts\]\s*\n((?:[^\[\n].*\n?)*)", text)
    if section:
        commands = re.findall(r"^\s*([\w.-]+)\s*=", section.group(1), re.M)
    return {
        "name": _regex_field(text, "name"),
        "description": _regex_field(text, "description"),
        "version": _regex_field(text, "version"),
        "commands": commands,
    }


def parse_package_json(text: str) -> dict:
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    bins = data.get("bin", {})
    commands = list(bins) if isinstance(bins, dict) else ([data.get("name", "")] if bins else [])
    return {
        "name": data.get("name", ""),
        "description": data.get("description", ""),
        "version": data.get("version", ""),
        "commands": [c for c in commands if c],
        "has_start": "start" in data.get("scripts", {}),
    }


def parse_remote(config_text: str) -> str:
    match = re.search(r"url\s*=\s*(\S+)", config_text)
    if not match:
        return ""
    url = match.group(1)
    ssh = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", url)
    if ssh:
        return f"https://{ssh.group(1)}/{ssh.group(2)}"
    return re.sub(r"\.git$", "", url) if url.startswith("http") else ""


def detect_license(text: str) -> str:
    for signature, name in LICENSE_SIGNATURES:
        if signature.lower() in text.lower():
            if name == "GPL" and "version 3" in text.lower():
                return "GPL-3.0"
            return name
    return "Custom" if text.strip() else ""


def build_tree(root: Path, limit: int = 30) -> str:
    lines: list[str] = ["."]

    def visible(p: Path) -> bool:
        return p.name not in SKIP_DIRS and (not p.name.startswith(".") or p.name == ".github")

    def walk(folder: Path, prefix: str, depth: int) -> None:
        entries = sorted((p for p in folder.iterdir() if visible(p)), key=lambda p: (p.is_file(), p.name.lower()))
        for i, entry in enumerate(entries):
            if len(lines) >= limit:
                return
            last = i == len(entries) - 1
            lines.append(f"{prefix}{'`-- ' if last else '|-- '}{entry.name}{'/' if entry.is_dir() else ''}")
            if entry.is_dir() and depth < 2:
                walk(entry, prefix + ("    " if last else "|   "), depth + 1)

    walk(root, "", 1)
    return "\n".join(lines)


def analyze(root: Path) -> Project:
    root = Path(root).resolve()
    files = list_files(root)
    project = Project(name=root.name)
    meta: dict = {}
    if "pyproject.toml" in files:
        meta, project.ecosystem = parse_pyproject(read_text(root / "pyproject.toml")), "python"
    elif "package.json" in files:
        meta, project.ecosystem = parse_package_json(read_text(root / "package.json")), "node"
    elif "Cargo.toml" in files:
        text = read_text(root / "Cargo.toml")
        meta = {"name": _regex_field(text, "name"), "description": _regex_field(text, "description"),
                "version": _regex_field(text, "version")}
        project.ecosystem = "rust"
    elif "go.mod" in files:
        module = re.search(r"^module\s+(\S+)", read_text(root / "go.mod"), re.M)
        meta = {"name": module.group(1).split("/")[-1] if module else ""}
        project.ecosystem = "go"
    elif "requirements.txt" in files or any(f.endswith(".py") for f in files):
        project.ecosystem = "python"

    project.name = meta.get("name") or project.name
    project.description = meta.get("description", "")
    project.version = meta.get("version", "")
    project.commands = meta.get("commands", [])
    if meta.get("has_start") and not project.commands:
        project.main_file = "npm start"

    counts = Counter(LANGS[Path(f).suffix] for f in files if Path(f).suffix in LANGS)
    project.languages = [lang for lang, _ in counts.most_common(4)]

    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
        if name in files:
            project.license = detect_license(read_text(root / name))
            break

    project.has_tests = any(
        {"tests", "test", "__tests__"} & set(f.lower().split("/")[:-1])
        or Path(f).name.startswith("test_") or Path(f).name.endswith(("_test.go", ".test.js", ".test.ts"))
        for f in files
    )
    workflows = [f for f in files if f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml"))]
    project.workflow = Path(workflows[0]).name if workflows else ""
    project.repo_url = parse_remote(read_text(root / ".git" / "config"))

    if project.ecosystem == "python" and not project.commands:
        for candidate in ("main.py", "app.py", f"{project.name}.py"):
            if candidate in files:
                project.main_file = f"python {candidate}"
                break
    project.tree = build_tree(root)
    return project


def banner_svg(name: str, tagline: str, languages: list, theme: str = "green") -> str:
    c1, c2 = THEMES[theme]
    size = max(28, min(64, int(780 / (0.62 * max(len(name), 1)))))
    shown = tagline if len(tagline) <= 72 else tagline[:69] + "..."
    cursor_x = 62 + int(len(shown) * 20 * 0.55)
    chips, x = [], 62
    for i, lang in enumerate(languages[:4]):
        w = int(24 + 8.2 * len(lang))
        chips.append(
            f'<g class="fade" style="animation-delay:{0.8 + i * 0.2:.1f}s">'
            f'<rect x="{x}" y="176" width="{w}" height="28" rx="14" fill="#1f2a37" stroke="#2d3b4b"/>'
            f'<text x="{x + w / 2:g}" y="195" text-anchor="middle" fill="{c2}">{escape(lang)}</text></g>'
        )
        x += w + 10
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="900" height="240" viewBox="0 0 900 240" role="img" aria-label="@LABEL@">
  <title>@LABEL@</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0d1117"/><stop offset="1" stop-color="#151b2b"/></linearGradient>
    <linearGradient id="ac" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="@C1@"/><stop offset="1" stop-color="@C2@"/></linearGradient>
    <pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1" fill="#30363d"/></pattern>
  </defs>
  <style>
    .sans { font-family: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; }
    .orb1 { animation: float1 7s ease-in-out infinite; } .orb2 { animation: float2 9s ease-in-out infinite; }
    .orb3 { animation: float1 11s ease-in-out infinite reverse; }
    .sweep { stroke-dasharray: 220 680; animation: sweep 3.2s linear infinite; }
    .cursor { animation: blink 1s steps(1) infinite; }
    .title { opacity: 0; animation: rise .8s ease-out .1s forwards; }
    .tag { opacity: 0; animation: rise .8s ease-out .4s forwards; }
    .fade { opacity: 0; animation: rise .6s ease-out forwards; }
    @keyframes float1 { 0%,100% { transform: translate(0,0); } 50% { transform: translate(24px,-18px); } }
    @keyframes float2 { 0%,100% { transform: translate(0,0); } 50% { transform: translate(-30px,16px); } }
    @keyframes sweep { to { stroke-dashoffset: -900; } }
    @keyframes blink { 50% { opacity: 0; } }
    @keyframes rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
  </style>
  <rect width="900" height="240" rx="18" fill="url(#bg)"/>
  <rect width="900" height="240" rx="18" fill="url(#dots)"/>
  <circle class="orb1" cx="760" cy="60" r="70" fill="@C1@" opacity=".16"/>
  <circle class="orb2" cx="840" cy="190" r="48" fill="@C2@" opacity=".18"/>
  <circle class="orb3" cx="660" cy="170" r="30" fill="@C1@" opacity=".12"/>
  <rect x=".5" y=".5" width="899" height="239" rx="17.5" fill="none" stroke="#30363d"/>
  <text class="sans title" x="60" y="104" font-size="@SIZE@" font-weight="800" fill="url(#ac)">@TITLE@</text>
  <path class="sweep" d="M62 122 H838" stroke="url(#ac)" stroke-width="3" stroke-linecap="round" fill="none"/>
  <text class="sans tag" x="62" y="158" font-size="20" fill="#8b949e">@TAG@</text>
  <rect class="cursor" x="@CURX@" y="141" width="10" height="20" fill="@C2@"/>
  <g class="sans" font-size="13" font-weight="600">@CHIPS@</g>
</svg>
"""
    for token, value in {
        "@LABEL@": escape(f"{name}: {shown}"), "@C1@": c1, "@C2@": c2, "@SIZE@": str(size),
        "@TITLE@": escape(name), "@TAG@": escape(shown), "@CURX@": str(cursor_x), "@CHIPS@": "".join(chips),
    }.items():
        svg = svg.replace(token, value)
    return svg


def render_readme(p: Project, banner_path: str | None) -> str:
    primary = p.languages[0] if p.languages else "software"
    tagline = p.description or f"A {primary} project."
    out = []
    if banner_path:
        out.append(f'<p align="center">\n  <img src="{banner_path}" alt="{p.name} banner" width="100%">\n</p>\n')
    badges = []
    if p.repo_url and p.workflow and p.repo_url.startswith("https://github.com/"):
        badges.append(f'<a href="{p.repo_url}/actions"><img src="{p.repo_url}/actions/workflows/{p.workflow}/badge.svg" alt="CI"></a>')
    if p.languages:
        badges.append(f'<img src="https://img.shields.io/badge/language-{p.languages[0].replace("+", "%2B").replace("#", "%23")}-blue" alt="{p.languages[0]}">')
    if p.license:
        badges.append(f'<img src="https://img.shields.io/badge/license-{p.license}-blue" alt="{p.license} license">')
    if badges:
        out.append('<p align="center">\n  ' + "\n  ".join(badges) + "\n</p>\n")
    out.append(f"**{p.name}**: {tagline}\n")

    glance = []
    if p.languages:
        glance.append("Written in " + ", ".join(p.languages))
    if p.has_tests:
        glance.append("Includes automated tests")
    if p.workflow:
        glance.append("Continuous integration with GitHub Actions")
    if p.license:
        glance.append(f"Released under the {p.license} license")
    if glance:
        out.append("## At a glance\n\n" + "\n".join(f"- {g}" for g in glance) + "\n")

    steps = []
    if p.repo_url:
        steps.append(f"git clone {p.repo_url}.git\ncd {p.repo_url.rstrip('/').split('/')[-1]}")
    steps += {
        "python": ["pip install ."], "node": ["npm install"],
        "rust": ["cargo build --release"], "go": ["go build ./..."],
    }.get(p.ecosystem, [])
    if steps:
        out.append("## Installation\n\n```bash\n" + "\n".join(steps) + "\n```\n")

    usage = ""
    if p.commands:
        usage = f"{p.commands[0]} --help"
    elif p.main_file:
        usage = p.main_file
    elif p.ecosystem == "rust":
        usage = "cargo run"
    elif p.ecosystem == "go":
        usage = "go run ."
    if usage:
        out.append(f"## Usage\n\n```bash\n{usage}\n```\n")

    out.append(f"## Project structure\n\n```text\n{p.tree}\n```\n")
    if p.license:
        out.append(f"## License\n\nReleased under the {p.license} license. See [LICENSE](LICENSE).\n")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="readmeforge", description="Generate a README and an animated banner.")
    parser.add_argument("path", nargs="?", default=".", help="project folder (default: current directory)")
    parser.add_argument("--out", default="README.md", help="README file to write, relative to the project")
    parser.add_argument("--banner", default="assets/banner.svg", help="banner path, relative to the project")
    parser.add_argument("--no-banner", action="store_true", help="skip the SVG banner")
    parser.add_argument("--theme", choices=sorted(THEMES), default="green", help="banner colors")
    parser.add_argument("--title", help="override the detected project name")
    parser.add_argument("--tagline", help="override the detected description")
    parser.add_argument("--force", action="store_true", help="overwrite an existing README")
    parser.add_argument("--dry-run", action="store_true", help="print the README instead of writing files")
    parser.add_argument("--version", action="version", version=f"readmeforge {__version__}")
    args = parser.parse_args(argv)

    root = Path(args.path)
    if not root.is_dir():
        print(f"readmeforge: not a directory: {args.path}", file=sys.stderr)
        return 2

    project = analyze(root)
    if args.title:
        project.name = args.title
    if args.tagline:
        project.description = args.tagline
    banner_rel = None if args.no_banner else args.banner
    readme = render_readme(project, banner_rel)

    if args.dry_run:
        print(readme)
        return 0
    target = root / args.out
    if target.exists() and not args.force:
        print(f"readmeforge: {args.out} already exists (use --force to overwrite)", file=sys.stderr)
        return 1
    if banner_rel:
        banner_file = root / banner_rel
        banner_file.parent.mkdir(parents=True, exist_ok=True)
        tagline = project.description or f"A {project.languages[0] if project.languages else 'software'} project."
        banner_file.write_text(banner_svg(project.name, tagline, project.languages, args.theme), encoding="utf-8")
    target.write_text(readme, encoding="utf-8")
    print(f"wrote {args.out}" + (f" and {banner_rel}" if banner_rel else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
