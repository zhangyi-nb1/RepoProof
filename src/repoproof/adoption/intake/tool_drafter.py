"""LLM 起草层(M2-d · RFC-010 [G1]:LLM 限草稿层)。

职责:把 intake 缺口清单里 **owner=LLM** 的字段起草进 draft 束
(statement/summary/接口格式/output_schema/reference 草稿/样例建议)。
边界(章程原文级):
  - 起草产物仍是 DRAFT —— 必须过 D 系确认闸 + 人确认才可冻结;
  - drafter 永不触碰 confirm/冻结/oracle;样例**真值**(文件与期望)
    仍归 USER,drafter 只给建议;
  - reference_impl 只在"仍是骨架"时覆盖 —— 人已写的内容一个字不动;
  - 每次起草落 draft_meta.json(模型/用量/起草字段),质量可追账。

通道:REPOPROOF_DRAFTER_MODEL/_BASE/_KEY 显式配置,缺省回落官方三键
(REPOPROOF_MODEL/REPOPROOF_API_BASE/REPOPROOF_API_KEY)—— 起草层是
产品自身的智能,不是被测 agent;共用通道但台账身份分明(meta 记账)。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

from repoproof.adoption.intake.tool_confirm import DRAFT_YAML, EXAMPLES_YAML, REFERENCE_PY
from repoproof.adoption.intake.tool_intake import ToolIntakeReport

_LLM_FIELDS = ("tool.summary", "tool.interface.input.format",
               "tool.interface.output.format", "capability.statement",
               "capability.output_schema", "reference_impl")

_SYSTEM = (
    "You draft ONE structured proposal for packaging a single capability of a "
    "pinned open-source Python library as a local CLI tool. Output STRICT JSON "
    "only (no markdown fences) with exactly these keys: summary (one line, "
    "same language as the goal), input_format (short format name like PDF/"
    "HTML/CSV), output_format, output_schema (CamelCase identifier), "
    "statement (the task statement: capability description PLUS behaviour "
    "definition — rendering/normalisation rules, edge semantics; state that "
    "malformed/empty input raises UserInputError (exit 1), repeated runs are "
    "deterministic, fully offline), reference_impl (python source: import the "
    "upstream module, define class UserInputError(ValueError), def "
    "extract(input_path: Path) -> str that REALLY calls the upstream and "
    "wraps bad-input errors as UserInputError), example_suggestions (list of "
    "{description, assertion_kind: contains|exact_file} — suggestions only; "
    "the human supplies actual files). No extra keys."
)


class DraftError(RuntimeError):
    pass


class FakeDrafter:
    """确定性模板起草(测试/离线):机制与真 LLM 同一接口同一落笔路径。"""

    name = "fake-drafter"

    def draft(self, context: dict) -> dict:
        goal = context["capability_goal"]
        mod = context["import_module"] or "upstream"
        return {
            "summary": f"{goal}(fake 起草)",
            "input_format": "DATA",
            "output_format": "TEXT",
            "output_schema": "DraftedOutput",
            "statement": (
                f"{goal}。行为定义(fake 起草,人须复核):输出确定性文本;"
                "坏输入抛 UserInputError(exit 1);重复调用确定;完全离线。"),
            "reference_impl": (
                '"""reference(fake 起草,人须复核):真调 pinned 上游。"""\n'
                "from pathlib import Path\n\n"
                f"import {mod}\n\n\n"
                "class UserInputError(ValueError):\n    pass\n\n\n"
                "def extract(input_path: Path) -> str:\n"
                "    data = input_path.read_text(encoding=\"utf-8\")\n"
                "    if not data.strip():\n"
                "        raise UserInputError(\"empty input\")\n"
                f"    return str({mod})\n"),
            "example_suggestions": [
                {"description": "一个典型输入文件 → contains 断言关键输出",
                 "assertion_kind": "contains"},
                {"description": "一个小输入 → 全文精确比对(expected_file)",
                 "assertion_kind": "exact_file"},
            ],
        }


class LiteLLMDrafter:
    """真 LLM 起草(litellm 通道;JSON 解析失败重试一次后如实抛)。"""

    def __init__(self) -> None:
        self.model = (os.environ.get("REPOPROOF_DRAFTER_MODEL")
                      or os.environ.get("REPOPROOF_MODEL") or "")
        self.api_base = (os.environ.get("REPOPROOF_DRAFTER_BASE")
                         or os.environ.get("REPOPROOF_API_BASE") or "")
        self.api_key = (os.environ.get("REPOPROOF_DRAFTER_KEY")
                        or os.environ.get("REPOPROOF_API_KEY") or "")
        if not (self.model and self.api_base and self.api_key):
            raise DraftError(
                "起草通道未配置:需 REPOPROOF_DRAFTER_*(或回落官方三键 "
                "REPOPROOF_MODEL/REPOPROOF_API_BASE/REPOPROOF_API_KEY)")
        self.name = f"litellm:{self.model}"
        self.last_usage: dict = {}

    def _once(self, user_msg: str) -> str:
        import litellm

        resp = litellm.completion(
            model=self.model, api_base=self.api_base, api_key=self.api_key,
            temperature=0,
            messages=[{"role": "system", "content": _SYSTEM},
                      {"role": "user", "content": user_msg}])
        u = getattr(resp, "usage", None)
        if u is not None:
            self.last_usage = {"prompt_tokens": getattr(u, "prompt_tokens", None),
                               "completion_tokens": getattr(u, "completion_tokens", None)}
        return resp.choices[0].message.content or ""

    def draft(self, context: dict) -> dict:
        user_msg = json.dumps(context, ensure_ascii=False, indent=1)
        text = self._once(user_msg)
        for attempt in (1, 2):
            try:
                body = text.strip()
                if body.startswith("```"):
                    body = body.strip("`\n")
                    body = body[body.index("{"):]
                return json.loads(body[body.index("{"): body.rindex("}") + 1])
            except (ValueError, IndexError):
                if attempt == 2:
                    raise DraftError(f"起草输出无法解析为 JSON:{text[:300]}")
                text = self._once(
                    user_msg + "\n\nYour previous output was not valid JSON. "
                    "Output ONLY the JSON object.")
        raise DraftError("unreachable")


def _drafter_context(report_like: dict) -> dict:
    """喂给起草器的最小上下文(确定性抽取,不塞全仓)。"""
    repo = report_like.get("repo") or {}
    return {
        "capability_goal": report_like.get("capability_goal", ""),
        "distribution": ((report_like.get("draft") or {}).get("source_repo")
                         or {}).get("distribution", ""),
        "import_module": ((report_like.get("draft") or {}).get("source_repo")
                          or {}).get("import_module", ""),
        "public_api": [str(f.get("value")) for f in
                       (repo.get("public_api") or [])[:20]],
        "cli_entry_points": [str(f.get("value")) for f in
                             (repo.get("cli_entry_points") or [])[:10]],
        "capability_candidates": [str(c) for c in
                                  (repo.get("capability_candidates") or [])[:10]],
        "tool_name": ((report_like.get("draft") or {}).get("tool")
                      or {}).get("name", ""),
    }


def draft_into_bundle(report: ToolIntakeReport, draft_dir: Path,
                      drafter) -> dict:
    """起草并写回 draft 束;返回 {fields_drafted, skipped, meta_path}。"""
    draft_dir = Path(draft_dir)
    draft_p = draft_dir / DRAFT_YAML
    if not draft_p.is_file():
        raise DraftError(f"{DRAFT_YAML} 不存在:{draft_p}(先跑 tool-intake --draft-out)")
    drafted = drafter.draft(_drafter_context(report.model_dump()))
    missing = [k for k in ("summary", "input_format", "output_format",
                           "output_schema", "statement", "reference_impl")
               if not str(drafted.get(k) or "").strip()]
    if missing:
        raise DraftError(f"起草结果缺键:{missing}")

    doc = yaml.safe_load(draft_p.read_text(encoding="utf-8")) or {}
    fields: list[str] = []

    def _fill(path: list[str], value: str) -> None:
        node = doc
        for key in path[:-1]:
            node = node.setdefault(key, {})
        if not str(node.get(path[-1]) or "").strip():   # 人已填的不覆盖
            node[path[-1]] = value
            fields.append(".".join(path))

    _fill(["tool", "summary"], drafted["summary"])
    _fill(["tool", "interface", "input", "format"], drafted["input_format"])
    _fill(["tool", "interface", "output", "format"], drafted["output_format"])
    _fill(["capability", "statement"], drafted["statement"])
    _fill(["capability", "output_schema"], drafted["output_schema"])
    draft_p.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
                       encoding="utf-8")

    skipped: list[str] = []
    ref_p = draft_dir / REFERENCE_PY
    ref_now = ref_p.read_text(encoding="utf-8") if ref_p.is_file() else ""
    if ("TODO" in ref_now) or ("NotImplementedError" in ref_now) or not ref_now:
        ref_p.write_text(drafted["reference_impl"], encoding="utf-8")
        fields.append("reference_impl")
    else:
        skipped.append("reference_impl(人已写,不覆盖)")

    suggestions = drafted.get("example_suggestions") or []
    if suggestions:
        ex_p = draft_dir / EXAMPLES_YAML
        lines = [f"# 起草层建议(仅建议;真值文件归人放置):",
                 *[f"#   - {s.get('description')}({s.get('assertion_kind')})"
                   for s in suggestions]]
        ex_p.write_text("\n".join(lines) + "\n"
                        + (ex_p.read_text(encoding="utf-8")
                           if ex_p.is_file() else "examples: []\n"),
                        encoding="utf-8")

    meta_path = draft_dir / "draft_meta.json"
    meta_path.write_text(json.dumps({
        "drafter": getattr(drafter, "name", type(drafter).__name__),
        "usage": getattr(drafter, "last_usage", {}),
        "fields_drafted": fields,
        "skipped": skipped,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"fields_drafted": fields, "skipped": skipped,
            "meta_path": str(meta_path)}
