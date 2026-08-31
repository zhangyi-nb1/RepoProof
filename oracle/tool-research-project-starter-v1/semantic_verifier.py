from pathlib import Path
import ast
import json
import re
import tempfile
import unicodedata
import yaml


def _read_utf8(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _input_values(input_path: Path):
    text = _read_utf8(input_path)
    if text is None:
        return None, None
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        return None, None
    if not isinstance(document, dict):
        return None, None
    title = document.get("title")
    description = document.get("description", "")
    if not isinstance(title, str) or not title.strip() or not isinstance(description, str):
        return None, None
    return title.strip(), description


def _distribution_name(title: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return name or "project"


def _module_project_name(tree: ast.AST):
    for node in getattr(tree, "body", []):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "PROJECT_NAME":
                return value.value
    return None


def _dotted_name(node: ast.AST):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return (base + "." if base else "") + node.attr
    return None


def _contains_string(node: ast.AST, value: str) -> bool:
    return any(isinstance(item, ast.Constant) and item.value == value for item in ast.walk(node))


def _contains_file_name(node: ast.AST) -> bool:
    return any(isinstance(item, ast.Name) and item.id == "__file__" for item in ast.walk(node))


def _runner_is_contractual(tree: ast.Module) -> bool:
    main_node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    if main_node is None:
        return False

    assignments = {}
    for node in ast.walk(main_node):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            assignments[node.targets[0].id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            assignments[node.target.id] = node.value

    def expanded(expr, seen=frozenset()):
        if isinstance(expr, ast.Name) and expr.id in assignments and expr.id not in seen:
            return expanded(assignments[expr.id], seen | {expr.id})
        return expr

    has_src_path = False
    has_discovery = False
    has_result_status = False
    for node in ast.walk(main_node):
        if not isinstance(node, ast.Call):
            continue
        called = _dotted_name(node.func)
        if called in {"sys.path.insert", "sys.path.append"}:
            relevant = [expanded(arg) for arg in node.args]
            if any(_contains_string(arg, "src") for arg in relevant) and any(_contains_file_name(arg) for arg in relevant):
                has_src_path = True
        if called == "unittest.defaultTestLoader.discover":
            relevant = [expanded(arg) for arg in node.args]
            relevant.extend(expanded(keyword.value) for keyword in node.keywords if keyword.arg in {"start_dir", "top_level_dir"})
            if any(_contains_string(arg, "tests") for arg in relevant) and any(_contains_file_name(arg) for arg in relevant):
                has_discovery = True
        if called and called.endswith(".wasSuccessful"):
            has_result_status = True

    has_return = any(isinstance(node, ast.Return) for node in ast.walk(main_node))
    exits_with_main = False
    for node in tree.body:
        for call in ast.walk(node):
            if not isinstance(call, ast.Call) or _dotted_name(call.func) != "SystemExit" or len(call.args) != 1:
                continue
            argument = call.args[0]
            if isinstance(argument, ast.Call) and _dotted_name(argument.func) == "main":
                exits_with_main = True
    return has_src_path and has_discovery and has_result_status and has_return and exits_with_main


def _render_upstream_values(title: str, description: str, distribution_name: str):
    try:
        from cookiecutter.main import cookiecutter
    except ImportError:
        return None
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        template = root / "template"
        rendered = template / "{{ cookiecutter.output_dir }}"
        rendered.mkdir(parents=True)
        (template / "cookiecutter.json").write_text(
            '{"output_dir":"rendered","title":"Project",'
            '"description":"","distribution_name":"project"}\n',
            encoding="utf-8",
        )
        (rendered / "values.json").write_text(
            '{"title":{{ cookiecutter.title | tojson }},'
            '"description":{{ cookiecutter.description | tojson }},'
            '"distribution_name":{{ cookiecutter.distribution_name | tojson }}}\n',
            encoding="utf-8",
        )
        try:
            result = Path(cookiecutter(
                str(template),
                no_input=True,
                extra_context={
                    "output_dir": "rendered",
                    "title": title,
                    "description": description,
                    "distribution_name": distribution_name,
                },
                output_dir=str(root / "output"),
            ))
            return json.loads((result / "values.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, KeyError):
            return None


def verify(input_path: Path, artifact_path: Path) -> dict:
    reasons = []
    checked = []

    title, description = _input_values(input_path)
    if title is None:
        reasons.append("CONTRACT_INPUT_TITLE_UNSPECIFIED")
        return {"ok": False, "reason_codes": reasons, "checked_commitment_ids": checked}
    expected_name = _distribution_name(title)
    upstream_values = _render_upstream_values(title, description, expected_name)
    if upstream_values is None:
        reasons.append("UPSTREAM_COOKIECUTTER_UNAVAILABLE")
        upstream_values = {}
    expected_title = upstream_values.get("title")
    expected_description = upstream_values.get("description")
    expected_name = upstream_values.get("distribution_name")

    project = artifact_path / "project"
    expected_paths = {
        "project/README.md",
        "project/pyproject.toml",
        "project/.gitignore",
        "project/src/starter_project/__init__.py",
        "project/tests/test_smoke.py",
        "project/run_tests.py",
        "project/config/experiment.yaml",
        "project/scripts/bootstrap.sh",
        "project/.github/workflows/ci.yml",
        "project/REPRODUCING.md",
    }

    checked.append("title-from-input")
    readme = _read_utf8(project / "README.md")
    readme_lines = readme.splitlines() if readme is not None else None
    if readme_lines is None or not readme_lines or readme_lines[0] != "# " + str(expected_title) or sum(line.startswith("# ") for line in readme_lines) != 1:
        reasons.append("README_TITLE_MISMATCH")

    checked.append("description-preservation")
    start_marker = "<!-- project-description-start -->"
    end_marker = "<!-- project-description-end -->"
    if readme_lines is None or readme_lines.count(start_marker) != 1 or readme_lines.count(end_marker) != 1:
        reasons.append("README_DESCRIPTION_MARKERS_INVALID")
    else:
        start = readme_lines.index(start_marker)
        end = readme_lines.index(end_marker)
        if end <= start or "\n".join(readme_lines[start + 1:end]) != expected_description:
            reasons.append("README_DESCRIPTION_MISMATCH")

    checked.append("normalized-distribution-name")
    pyproject_text = _read_utf8(project / "pyproject.toml")
    actual_name = None
    if pyproject_text is not None:
        try:
            import tomllib
            parsed = tomllib.loads(pyproject_text)
            actual_name = parsed.get("project", {}).get("name")
        except (ImportError, ValueError):
            actual_name = None
    if not isinstance(actual_name, str) or actual_name != expected_name or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", actual_name):
        reasons.append("PYPROJECT_DISTRIBUTION_NAME_MISMATCH")

    checked.append("starter-module-title")
    module_text = _read_utf8(project / "src" / "starter_project" / "__init__.py")
    actual_title = None
    if module_text is not None:
        try:
            actual_title = _module_project_name(ast.parse(module_text))
        except SyntaxError:
            actual_title = None
    if actual_title != expected_title:
        reasons.append("STARTER_MODULE_TITLE_MISMATCH")

    checked.append("starter-layout")
    actual_paths = set()
    try:
        if artifact_path.exists():
            actual_paths = {path.relative_to(artifact_path).as_posix() for path in artifact_path.rglob("*") if path.is_file()}
    except OSError:
        actual_paths = set()
    if actual_paths != expected_paths:
        reasons.append("WORKSPACE_LAYOUT_MISMATCH")

    checked.append("direct-test-entrypoint")
    runner_text = _read_utf8(project / "run_tests.py")
    runner_ok = False
    if runner_text is not None:
        try:
            runner_ok = _runner_is_contractual(ast.parse(runner_text))
        except SyntaxError:
            runner_ok = False
    if not runner_ok:
        reasons.append("TEST_RUNNER_SEMANTICS_MISMATCH")

    checked.append("handoff-support-assets")
    config_text = _read_utf8(project / "config" / "experiment.yaml") or ""
    bootstrap_text = _read_utf8(project / "scripts" / "bootstrap.sh") or ""
    ci_text = _read_utf8(project / ".github" / "workflows" / "ci.yml") or ""
    reproducing_text = _read_utf8(project / "REPRODUCING.md") or ""
    if (
        "schema_version: 1" not in config_text
        or f"project_name: {json.dumps(expected_title, ensure_ascii=False)}" not in config_text
        or "random_seed: 42" not in config_text
    ):
        reasons.append("EXPERIMENT_CONFIG_MISMATCH")
    if "python3 -m venv .venv" not in bootstrap_text or ".venv/bin/python run_tests.py" not in bootstrap_text:
        reasons.append("BOOTSTRAP_SCRIPT_MISMATCH")
    if "actions/checkout@v4" not in ci_text or "python run_tests.py" not in ci_text:
        reasons.append("CI_WORKFLOW_MISMATCH")
    if "python3 -m venv .venv" not in reproducing_text or "config/experiment.yaml" not in reproducing_text:
        reasons.append("REPRODUCTION_GUIDE_MISMATCH")

    return {"ok": not reasons, "reason_codes": reasons, "checked_commitment_ids": checked}
