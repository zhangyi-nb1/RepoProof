"""LLM 起草层(M2-d · RFC-010 [G1]:LLM 限草稿层)。

职责:把 intake 缺口清单里 **owner=LLM** 的字段起草进 draft 束
(statement/summary/接口格式/output_schema/reference 草稿/样例建议)。
边界(章程原文级):
  - 起草产物仍是 DRAFT —— 必须过 D 系确认闸 + 人确认才可冻结;
  - drafter 永不触碰 confirm/冻结/oracle;样例**真值**(文件与期望)
    仍归 USER,drafter 只给建议;
  - reference_impl 只在"仍是骨架"时覆盖 —— 人已写的内容一个字不动;
  - 每次起草落 draft_meta.json(模型/用量/起草字段),质量可追账。

通道:产品默认走 LiteLLM + 私有 OpenAI-compatible API 网关；
`REPOPROOF_DRAFTER_BACKEND=codex-cli` 可显式切到官方 Codex CLI +
本机 ChatGPT OAuth 回退通道。起草层是产品自身的智能,不是被测
agent;台账身份由 meta 分明记录。
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from repoproof.adoption.intake.tool_confirm import DRAFT_YAML, EXAMPLES_YAML, REFERENCE_PY
from repoproof.adoption.intake.tool_intake import ToolIntakeReport

_LLM_FIELDS = ("tool.summary", "tool.interface.input.format",
               "tool.interface.output.format", "tool.interface.output.contract",
               "capability.statement",
               "capability.output_schema", "reference_impl")

_SUMMARY_SYSTEM = (
    "You write a SHORT plain-language summary (Chinese unless the excerpt is "
    "clearly another language) of what an open-source repository does, for a "
    "user who is about to decide which single capability to extract from it. "
    "Use ONLY the given README excerpt and entry-point list; if something is "
    "not in them, say you cannot tell rather than guessing. 3-5 sentences. "
    "Do NOT recommend which capability to pick and do NOT write the user's "
    "goal for them: choosing the capability is the human's decision."
)


_INPUTS_SYSTEM = (
    "You propose CANDIDATE INPUT FILES for testing a local CLI tool that wraps "
    "one capability of a pinned Python library. Output STRICT JSON only "
    "(no markdown fences): {\"inputs\": [{\"input_name\": \"...\", "
    "\"input_text\": \"...\", \"why\": \"...\"}]}. "
    "Cover a typical case AND edge cases (empty, whitespace, non-ASCII, "
    "malformed/invalid values) that would expose an under-specified contract. "
    "Return exactly `how_many` distinct inputs. If `failed_attempts` is present, "
    "do not repeat those inputs; use their upstream errors to propose alternatives "
    "that are more likely to exercise the requested capability successfully. "
    "`why` is one short line in the SAME LANGUAGE as capability_goal. "
    "NEVER include an expected output, expected value, assertion or verdict of "
    "any kind: the expected output is obtained by actually running the pinned "
    "upstream and is confirmed by the human. Inputs must be plain UTF-8 text."
)


_SYSTEM = (
    "You draft ONE structured proposal for packaging a single capability of a "
    "pinned open-source Python library as a local CLI tool. Output STRICT JSON "
    "only (no markdown fences) with exactly these keys: summary (one line, "
    "same language as the goal), input_format (short format name like PDF/"
    "HTML/CSV), output_format, output_schema (CamelCase identifier), "
    "output_contract (object with media_type, root_type and required; root_type "
    "is text/json/object/array/json_lines; required maps top-level JSON field "
    "names to any|string|integer|number|boolean|object|array|null), "
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

_CODEX_DRAFT_SYSTEM = (
    _SYSTEM.replace(
        "output_contract (object with media_type, root_type and required; root_type "
        "is text/json/object/array/json_lines; required maps top-level JSON field "
        "names to any|string|integer|number|boolean|object|array|null), ",
        "output_contract (object with media_type, root_type and required_fields; root_type "
        "is text/json/object/array/json_lines; required_fields is a list of objects with "
        "name and type, where type is any|string|integer|number|boolean|object|array|null), ",
    )
)


def _with_provider(model: str) -> str:
    """给自定义模型名补 `openai/` 前缀 —— 与产线(host_guided)同一口径。

    已经带 `<provider>/` 的原样返回:重复加前缀会变成 `openai/openai/x`。
    """
    m = (model or "").strip()
    return m if (not m or "/" in m) else f"openai/{m}"


class DraftError(RuntimeError):
    pass


_SUMMARY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary"],
    "properties": {
        "summary": {"type": "string", "minLength": 1, "maxLength": 2000},
    },
}

_OUTPUT_CONTRACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["media_type", "root_type", "required"],
    "properties": {
        "media_type": {"type": "string", "minLength": 1, "maxLength": 120},
        "root_type": {
            "type": "string",
            "enum": ["text", "json", "object", "array", "json_lines"],
        },
        "required": {
            "type": "object",
            "additionalProperties": {
                "type": "string",
                "enum": [
                    "any", "string", "integer", "number", "boolean",
                    "object", "array", "null",
                ],
            },
        },
    },
}

# OpenAI strict structured outputs require closed objects.  A JSON object whose
# keys are user-selected field names is therefore transported as a strict list
# and converted back to ToolOutputContract's canonical mapping locally.
_CODEX_OUTPUT_CONTRACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["media_type", "root_type", "required_fields"],
    "properties": {
        "media_type": {"type": "string", "minLength": 1, "maxLength": 120},
        "root_type": {
            "type": "string",
            "enum": ["text", "json", "object", "array", "json_lines"],
        },
        "required_fields": {
            "type": "array",
            "maxItems": 32,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "type"],
                "properties": {
                    "name": {"type": "string", "minLength": 1, "maxLength": 120},
                    "type": {
                        "type": "string",
                        "enum": [
                            "any", "string", "integer", "number", "boolean",
                            "object", "array", "null",
                        ],
                    },
                },
            },
        },
    },
}

_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "summary",
        "input_format",
        "output_format",
        "output_schema",
        "output_contract",
        "statement",
        "reference_impl",
        "example_suggestions",
    ],
    "properties": {
        "summary": {"type": "string", "minLength": 1, "maxLength": 500},
        "input_format": {"type": "string", "minLength": 1, "maxLength": 80},
        "output_format": {"type": "string", "minLength": 1, "maxLength": 80},
        "output_schema": {"type": "string", "minLength": 1, "maxLength": 120},
        "output_contract": _OUTPUT_CONTRACT_SCHEMA,
        "statement": {"type": "string", "minLength": 1, "maxLength": 5000},
        "reference_impl": {"type": "string", "minLength": 1, "maxLength": 30000},
        "example_suggestions": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["description", "assertion_kind"],
                "properties": {
                    "description": {"type": "string", "minLength": 1, "maxLength": 500},
                    "assertion_kind": {"type": "string", "enum": ["contains", "exact_file"]},
                },
            },
        },
    },
}

_CODEX_DRAFT_SCHEMA: dict[str, Any] = {
    **_DRAFT_SCHEMA,
    "properties": {
        **_DRAFT_SCHEMA["properties"],
        "output_contract": _CODEX_OUTPUT_CONTRACT_SCHEMA,
    },
}

_INPUTS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["inputs"],
    "properties": {
        "inputs": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["input_name", "input_text", "why"],
                "properties": {
                    "input_name": {"type": "string", "minLength": 1, "maxLength": 120},
                    "input_text": {"type": "string", "maxLength": 20000},
                    "why": {"type": "string", "minLength": 1, "maxLength": 500},
                },
            },
        },
    },
}


class CodexDrafter:
    """Subscription-backed, no-tool drafter for all Studio assistant actions."""

    def __init__(self) -> None:
        from repoproof.agents.codex_cli_backend import (
            run_subscription_preflight,
            subscription_config,
        )

        config = subscription_config()
        preflight = run_subscription_preflight(config)
        if config is None or not preflight.ready:
            raise DraftError(f"Codex 起草通道不可用:{preflight.status}")
        model_override = os.environ.get("REPOPROOF_CODEX_DRAFTER_MODEL", "").strip()
        self.config = replace(config, model_name=model_override) if model_override else config
        self.name = f"codex-cli:{self.config.model_name}"
        self.last_usage: dict = {}

    def _structured(
        self,
        *,
        instructions: str,
        context: dict,
        schema: dict,
        purpose: str,
    ) -> dict:
        from repoproof.agents.codex_text_client import CodexTextError, run_codex_structured

        try:
            result = run_codex_structured(
                config=self.config,
                instructions=instructions,
                context=context,
                schema=schema,
                purpose=purpose,
            )
        except CodexTextError as exc:
            raise DraftError(str(exc)) from exc
        self.last_usage = dict(result.usage)
        return result.document

    def draft(self, context: dict) -> dict:
        document = self._structured(
            instructions=_CODEX_DRAFT_SYSTEM,
            context=context,
            schema=_CODEX_DRAFT_SCHEMA,
            purpose="tool-draft",
        )
        raw_contract = document["output_contract"]
        required: dict[str, str] = {}
        for field in raw_contract.pop("required_fields"):
            name = field["name"].strip()
            if name in required:
                raise DraftError(f"tool-draft:CODEX_DUPLICATE_REQUIRED_FIELD:{name}")
            required[name] = field["type"]
        raw_contract["required"] = required
        try:
            import jsonschema

            jsonschema.validate(document, _DRAFT_SCHEMA)
        except jsonschema.ValidationError as exc:
            raise DraftError("tool-draft:CODEX_DRAFT_NORMALIZATION_INVALID") from exc
        return document

    def summarize_repo(self, context: dict) -> dict:
        return self._structured(
            instructions=_SUMMARY_SYSTEM + " Return an object with exactly the key summary.",
            context=context,
            schema=_SUMMARY_SCHEMA,
            purpose="repo-summary",
        )

    def propose_example_inputs(self, context: dict) -> dict:
        requested = max(1, min(int(context.get("how_many") or 4), 8))
        schema: dict[str, Any] = deepcopy(_INPUTS_SCHEMA)
        schema["properties"]["inputs"]["minItems"] = requested
        schema["properties"]["inputs"]["maxItems"] = requested
        return self._structured(
            instructions=_INPUTS_SYSTEM,
            context=context,
            schema=schema,
            purpose="example-candidates",
        )


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
            "output_contract": {
                "media_type": "text/plain", "root_type": "text", "required": {}},
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

    def summarize_repo(self, context: dict) -> dict:
        """仓库摘要(确定性模板)。产物只进展示层,不进 draft、不填能力描述。"""
        head = str(context.get("headline") or "").strip()
        n = len(context.get("surfaces") or [])
        return {"summary": f"(离线模板摘要)这个仓库自述为:{head[:120]}"
                           f"。静态扫描到 {n} 个公开入口。"}

    def propose_example_inputs(self, context: dict) -> dict:
        """候选**输入**(确定性模板)。只出输入 —— 期望输出由上游真跑给出。"""
        n = int(context.get("how_many") or 3)
        goal = context.get("capability_goal", "")
        # 证据候选优先:README 里作者亲手写的示例值,比任何通用模板都靠谱
        # (离线模板是域盲的 —— webcolors 实测 6 条通用候选全部让上游抛错)。
        mined = [str(x) for x in (context.get("evidence_literals") or [])]
        evidence = [{"input_name": f"from_readme_{i + 1}.txt", "input_text": lit,
                     "why": "README 示例里出现的输入(证据挖掘,非模型生成)"}
                    for i, lit in enumerate(mined)]
        shapes = [("typical.txt", "典型输入", "覆盖最常见的一种用法"),
                  ("edge_empty.txt", "", "空输入:边界行为必须被题面写死"),
                  ("edge_unicode.txt", "非 ASCII 输入 · 测试", "非 ASCII:编码路径"),
                  ("edge_long.txt", "x" * 200, "超长输入:截断/性能路径"),
                  ("edge_spaces.txt", "  前后空白  ", "首尾空白:规范化行为"),
                  ("edge_multiline.txt", "第一行\n第二行", "多行输入"),
                  ("edge_symbols.txt", "!@#$%^&*()", "符号输入:非法值路径"),
                  ("edge_numeric.txt", "1234567890", "纯数字输入")]
        generic = [{"input_name": nm, "input_text": txt or "",
                    "why": f"{why}(fake 起草;目标:{goal[:40]})"}
                   for nm, txt, why in shapes]
        return {"inputs": (evidence + generic)[:n]}


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
        # litellm 要能推断出 provider。裸名 `gpt-5.6-terra` 不在它的模型表里
        # (自建 OpenAI 兼容端点的自定义名基本都不在),推断失败就抛
        # "LLM Provider NOT provided"(2026-08-27 用户实测)。产线早就走
        # `openai/{model}`(host_guided 构造 LitellmModel 那处),起草器一直
        # 传裸名 —— 同一个通道两种写法,只有一种能用。这里对齐产线。
        self.model = _with_provider(self.model)
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
            except (ValueError, IndexError) as exc:
                if attempt == 2:
                    raise DraftError(
                        f"起草输出无法解析为 JSON:{text[:300]}") from exc
                text = self._once(
                    user_msg + "\n\nYour previous output was not valid JSON. "
                    "Output ONLY the JSON object.")
        raise DraftError("unreachable")

    def summarize_repo(self, context: dict) -> dict:
        """仓库摘要/翻译(真 LLM)。**展示件**:不进 draft,不参与判定。

        提示词显式要求"只依据给到的 README 摘录与入口清单",并且不得替
        用户判断该用哪个能力 —— 那是人闸的活。
        """
        text = self._once_with_system(
            _SUMMARY_SYSTEM, json.dumps(context, ensure_ascii=False, indent=1))
        return {"summary": text.strip()}

    def propose_example_inputs(self, context: dict) -> dict:
        """候选**输入**(真 LLM)。

        提示词刻意**不要**模型给期望输出:它给了也不会被采用,而让它给
        等于邀请它去猜判定 —— 判定的来源只能是上游真跑 + 人确认。
        """
        user_msg = json.dumps(context, ensure_ascii=False, indent=1)
        text = self._once_with_system(_INPUTS_SYSTEM, user_msg)
        for attempt in (1, 2):
            try:
                body = text.strip()
                if body.startswith("```"):
                    body = body.strip("`\n")
                    body = body[body.index("{"):]
                doc = json.loads(body[body.index("{"): body.rindex("}") + 1])
                if not isinstance(doc.get("inputs"), list):
                    raise ValueError("missing 'inputs' list")
                return doc
            except (ValueError, IndexError) as exc:
                if attempt == 2:
                    raise DraftError(
                        f"候选输入输出无法解析为 JSON:{text[:300]}") from exc
                text = self._once_with_system(
                    _INPUTS_SYSTEM,
                    user_msg + "\n\nYour previous output was not valid JSON. "
                    "Output ONLY the JSON object with an 'inputs' array.")
        raise DraftError("unreachable")

    def _once_with_system(self, system: str, user_msg: str) -> str:
        import litellm

        resp = litellm.completion(
            model=self.model, api_base=self.api_base, api_key=self.api_key,
            temperature=0,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user_msg}])
        u = getattr(resp, "usage", None)
        if u is not None:
            self.last_usage = {"prompt_tokens": getattr(u, "prompt_tokens", None),
                               "completion_tokens": getattr(u, "completion_tokens", None)}
        return resp.choices[0].message.content or ""


def _litellm_ready() -> bool:
    """litellm 三键齐不齐(只看在不在,**不读值**)。"""
    return bool(
        (os.environ.get("REPOPROOF_DRAFTER_MODEL") or os.environ.get("REPOPROOF_MODEL"))
        and (os.environ.get("REPOPROOF_DRAFTER_BASE") or os.environ.get("REPOPROOF_API_BASE"))
        and (os.environ.get("REPOPROOF_DRAFTER_KEY") or os.environ.get("REPOPROOF_API_KEY"))
    )


def _codex_ready() -> bool:
    from repoproof.agents.codex_cli_backend import (
        run_subscription_preflight,
        subscription_config,
    )

    return bool(run_subscription_preflight(subscription_config()).ready)


def configured_drafter_backend() -> str:
    """起草后端:未指定 = API 网关(产品默认,见 2ab838f)。

    **不做自动回退**:网关没配就如实报"未配置",而不是悄悄改走 Codex ——
    换通道会换掉计费主体、模型身份与可复现性,这种事必须是操作员的显式
    决定。回退入口是显式的:`scripts/run_ui_codex.sh`(或
    `REPOPROOF_DRAFTER_BACKEND=codex-cli`)。UI 侧负责把"当前哪条通道、
    为什么不可用、怎么换"说清楚,而不是替人换。
    """
    raw = os.environ.get("REPOPROOF_DRAFTER_BACKEND", "litellm").strip().lower()
    aliases = {
        "codex": "codex-cli",
        "subscription": "codex-cli",
        "api": "litellm",
    }
    backend = aliases.get(raw, raw)
    if backend not in {"codex-cli", "litellm"}:
        raise DraftError(
            "未知起草 backend:需 codex-cli 或 litellm"
        )
    return backend


def online_drafter():
    """Build the configured online drafter without a silent fallback."""

    return CodexDrafter() if configured_drafter_backend() == "codex-cli" else LiteLLMDrafter()


def online_drafter_status() -> dict[str, str | bool]:
    """Read-only readiness for UI labels; never performs a model request."""

    try:
        backend = configured_drafter_backend()
    except DraftError as exc:
        return {"ready": False, "backend": "INVALID", "label": str(exc)}
    if backend == "litellm":
        ready = _litellm_ready()
        label = "API provider 已配置" if ready else "API provider 未配置"
        if not ready and _codex_ready():
            # 不替人换通道,但要让人知道**手边就有一条通的**(2026-08-28
            # 实测:用户被"未配置"挡住,而本机 Codex 订阅一直就绪)。
            label += "；本机 Codex 订阅可用，改用 scripts/run_ui_codex.sh 即可"
        return {"ready": ready, "backend": "litellm", "label": label}

    from repoproof.agents.codex_cli_backend import (
        run_subscription_preflight,
        subscription_config,
    )

    config = subscription_config()
    preflight = run_subscription_preflight(config)
    return {
        "ready": preflight.ready,
        "backend": "codex-cli",
        "label": (
            f"Codex CLI 已登录 · {config.model_name}"
            if preflight.ready and config is not None
            else f"Codex CLI 不可用 · {preflight.status}"
        ),
    }


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
                           "output_schema", "output_contract", "statement",
                           "reference_impl")
               if not str(drafted.get(k) or "").strip()]
    if missing:
        raise DraftError(f"起草结果缺键:{missing}")

    doc = yaml.safe_load(draft_p.read_text(encoding="utf-8")) or {}
    fields: list[str] = []

    def _fill(path: list[str], value) -> None:
        node = doc
        for key in path[:-1]:
            node = node.setdefault(key, {})
        current = node.get(path[-1])
        empty = (not current.strip()) if isinstance(current, str) else (not current)
        if empty:   # 人已填的不覆盖
            node[path[-1]] = value
            fields.append(".".join(path))

    _fill(["tool", "summary"], drafted["summary"])
    _fill(["tool", "interface", "input", "format"], drafted["input_format"])
    _fill(["tool", "interface", "output", "format"], drafted["output_format"])
    _fill(["tool", "interface", "output", "contract"], drafted["output_contract"])
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
        lines = ["# 起草层建议(仅建议;真值文件归人放置):",
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
