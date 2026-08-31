from pathlib import Path
import re
import tempfile
import unicodedata

from cookiecutter.main import cookiecutter
import yaml


class UserInputError(ValueError):
    pass


def _read_description(input_path: Path) -> tuple[str, str]:
    try:
        document = yaml.safe_load(input_path.read_text(encoding="utf-8"))
    except (
        FileNotFoundError,
        IsADirectoryError,
        PermissionError,
        UnicodeDecodeError,
        yaml.YAMLError,
    ) as exc:
        raise UserInputError("项目说明必须是可读取的 UTF-8 YAML 文件") from exc
    if not isinstance(document, dict):
        raise UserInputError("项目说明 YAML 的根节点必须是对象")
    title = document.get("title")
    description = document.get("description", "")
    if not isinstance(title, str) or not title.strip():
        raise UserInputError("项目说明必须包含非空字符串 title")
    if not isinstance(description, str):
        raise UserInputError("项目说明的 description 必须是字符串")
    return title.strip(), description


def _distribution_name(title: str) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    return slug or "project"


def _write_template(template_dir: Path) -> None:
    (template_dir / "cookiecutter.json").write_text(
        '{"directory_name":"project","project_name":"Project",'
        '"project_description":"","distribution_name":"project"}\n',
        encoding="utf-8",
    )
    project = template_dir / "{{ cookiecutter.directory_name }}"
    (project / "src" / "starter_project").mkdir(parents=True)
    (project / "tests").mkdir()
    (project / "config").mkdir()
    (project / "scripts").mkdir()
    (project / ".github" / "workflows").mkdir(parents=True)
    (project / "README.md").write_text(
        "# {{ cookiecutter.project_name }}\n\n"
        "<!-- project-description-start -->\n"
        "{{ cookiecutter.project_description }}\n"
        "<!-- project-description-end -->\n\n"
        "## 开始\n\n"
        "在此目录运行：\n\n"
        "```sh\n"
        "./run_tests.py\n"
        "```\n",
        encoding="utf-8",
    )
    (project / "pyproject.toml").write_text(
        "[project]\n"
        "name = {{ cookiecutter.distribution_name | tojson }}\n"
        "version = \"0.1.0\"\n"
        "description = {{ cookiecutter.project_description | tojson }}\n"
        "requires-python = \">=3.9\"\n",
        encoding="utf-8",
    )
    (project / ".gitignore").write_text("__pycache__/\n*.py[cod]\n.venv/\n", encoding="utf-8")
    (project / "src" / "starter_project" / "__init__.py").write_text(
        "\"\"\"Starter package for the generated project.\"\"\"\n\n"
        "PROJECT_NAME = {{ cookiecutter.project_name | tojson }}\n",
        encoding="utf-8",
    )
    (project / "tests" / "test_smoke.py").write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "import unittest\n\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n"
        "from starter_project import PROJECT_NAME\n\n"
        "class StarterProjectTests(unittest.TestCase):\n"
        "    def test_project_name_is_present(self):\n"
        "        self.assertTrue(PROJECT_NAME.strip())\n",
        encoding="utf-8",
    )
    runner = project / "run_tests.py"
    runner.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pathlib import Path\n"
        "import unittest\n\n"
        "def main():\n"
        "    root = Path(__file__).resolve().parent\n"
        "    sys.path.insert(0, str(root / 'src'))\n"
        "    suite = unittest.defaultTestLoader.discover(str(root / 'tests'))\n"
        "    result = unittest.TextTestRunner(verbosity=2).run(suite)\n"
        "    return 0 if result.wasSuccessful() else 1\n\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n",
        encoding="utf-8",
    )
    runner.chmod(0o755)
    (project / "config" / "experiment.yaml").write_text(
        "schema_version: 1\n"
        "project_name: {{ cookiecutter.project_name | tojson }}\n"
        "random_seed: 42\n",
        encoding="utf-8",
    )
    bootstrap = project / "scripts" / "bootstrap.sh"
    bootstrap.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "python3 -m venv .venv\n"
        ".venv/bin/python run_tests.py\n",
        encoding="utf-8",
    )
    bootstrap.chmod(0o755)
    (project / ".github" / "workflows" / "ci.yml").write_text(
        "name: checks\n"
        "on: [push, pull_request]\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: actions/setup-python@v5\n"
        "        with:\n"
        "          python-version: '3.12'\n"
        "      - run: python run_tests.py\n",
        encoding="utf-8",
    )
    (project / "REPRODUCING.md").write_text(
        "# Reproducing this starter project\n\n"
        "1. Create an isolated environment with `python3 -m venv .venv`.\n"
        "2. Run the deterministic smoke check with `.venv/bin/python run_tests.py`.\n"
        "3. Keep `config/experiment.yaml` under version control when parameters change.\n",
        encoding="utf-8",
    )


def build_workspace(input_path: Path, output_dir: Path) -> None:
    title, description = _read_description(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary_dir:
        template_dir = Path(temporary_dir) / "embedded-template"
        template_dir.mkdir()
        _write_template(template_dir)
        cookiecutter(
            str(template_dir),
            no_input=True,
            extra_context={
                "directory_name": "project",
                "project_name": title,
                "project_description": description,
                "distribution_name": _distribution_name(title),
            },
            output_dir=str(output_dir),
        )
