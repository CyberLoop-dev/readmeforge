import contextlib
import io
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import readmeforge  # noqa: E402

PYPROJECT = """[project]
name = "demo-tool"
version = "1.2.3"
description = "Does demo things quickly."

[project.scripts]
demo = "demo:main"
"""


def make_project(files):
    tmp = tempfile.TemporaryDirectory()
    for rel, content in files.items():
        path = Path(tmp.name, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp


class AnalyzeTests(unittest.TestCase):
    def test_python_project_metadata(self):
        files = {"pyproject.toml": PYPROJECT, "demo.py": "pass\n", "tests/test_demo.py": "pass\n"}
        with make_project(files) as d:
            p = readmeforge.analyze(Path(d))
        self.assertEqual((p.name, p.version, p.ecosystem), ("demo-tool", "1.2.3", "python"))
        self.assertEqual(p.description, "Does demo things quickly.")
        self.assertEqual(p.commands, ["demo"])
        self.assertTrue(p.has_tests)
        self.assertEqual(p.languages, ["Python"])

    def test_node_project(self):
        pkg = '{"name": "web-thing", "description": "A web thing", "bin": {"wt": "cli.js"}}'
        with make_project({"package.json": pkg, "cli.js": "1\n"}) as d:
            p = readmeforge.analyze(Path(d))
        self.assertEqual((p.name, p.ecosystem, p.commands), ("web-thing", "node", ["wt"]))
        self.assertEqual(p.languages, ["JavaScript"])

    def test_license_and_workflow_detection(self):
        files = {"LICENSE": "MIT License\n\nCopyright", ".github/workflows/ci.yml": "name: ci\n"}
        with make_project(files) as d:
            p = readmeforge.analyze(Path(d))
        self.assertEqual(p.license, "MIT")
        self.assertEqual(p.workflow, "ci.yml")

    def test_remote_parsing(self):
        self.assertEqual(readmeforge.parse_remote("url = git@github.com:me/repo.git"), "https://github.com/me/repo")
        self.assertEqual(readmeforge.parse_remote("url = https://github.com/me/repo.git"), "https://github.com/me/repo")
        self.assertEqual(readmeforge.parse_remote(""), "")

    def test_skips_vendor_folders_in_languages(self):
        with make_project({"a.py": "1\n", "node_modules/x/y.js": "1\n"}) as d:
            self.assertEqual(readmeforge.analyze(Path(d)).languages, ["Python"])


class RenderTests(unittest.TestCase):
    def test_banner_is_valid_xml_and_escapes_name(self):
        svg = readmeforge.banner_svg("a&b <tool>", "Fast & small", ["Python", "C++"], "purple")
        root = ET.fromstring(svg)
        self.assertTrue(root.tag.endswith("svg"))
        self.assertIn("a&amp;b &lt;tool&gt;", svg)
        self.assertIn("#a371f7", svg)

    def test_every_theme_renders(self):
        for theme in readmeforge.THEMES:
            ET.fromstring(readmeforge.banner_svg("x", "y", ["Go"], theme))

    def test_readme_sections(self):
        files = {"pyproject.toml": PYPROJECT, "demo.py": "pass\n", "LICENSE": "MIT License"}
        with make_project(files) as d:
            readme = readmeforge.render_readme(readmeforge.analyze(Path(d)), "assets/banner.svg")
        for expected in ("assets/banner.svg", "## Installation", "pip install .", "demo --help",
                         "## Project structure", "MIT license"):
            self.assertIn(expected, readme)

    def test_readme_without_banner(self):
        with make_project({"a.py": "1\n"}) as d:
            readme = readmeforge.render_readme(readmeforge.analyze(Path(d)), None)
        self.assertNotIn("banner", readme)


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = readmeforge.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_writes_readme_and_banner(self):
        with make_project({"pyproject.toml": PYPROJECT}) as d:
            code, out, _ = self.run_cli(d)
            self.assertEqual(code, 0)
            self.assertTrue(Path(d, "README.md").exists())
            ET.fromstring(Path(d, "assets/banner.svg").read_text(encoding="utf-8"))

    def test_refuses_to_overwrite_without_force(self):
        with make_project({"README.md": "mine\n"}) as d:
            code, _, err = self.run_cli(d)
            self.assertEqual(code, 1)
            self.assertIn("--force", err)
            self.assertEqual(Path(d, "README.md").read_text(), "mine\n")
            self.assertEqual(self.run_cli(d, "--force")[0], 0)
            self.assertNotEqual(Path(d, "README.md").read_text(), "mine\n")

    def test_dry_run_writes_nothing(self):
        with make_project({"pyproject.toml": PYPROJECT}) as d:
            code, out, _ = self.run_cli(d, "--dry-run")
            self.assertEqual(code, 0)
            self.assertIn("demo-tool", out)
            self.assertFalse(Path(d, "README.md").exists())

    def test_title_and_tagline_overrides(self):
        with make_project({"a.py": "1\n"}) as d:
            _, out, _ = self.run_cli(d, "--dry-run", "--title", "Zed", "--tagline", "Custom line.")
        self.assertIn("**Zed**: Custom line.", out)

    def test_bad_path_returns_2(self):
        self.assertEqual(self.run_cli("/definitely/not/here")[0], 2)


if __name__ == "__main__":
    unittest.main()
