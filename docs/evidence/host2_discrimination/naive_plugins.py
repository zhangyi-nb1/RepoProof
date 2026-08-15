"""朴素版 —— 一个没见过原件、只知道"要把 Flask 路由转成 OpenAPI 参数"的人
会写出来的东西。刻意用公开 API `rule.arguments`(原件用的是私有 `rule._trace`),
且不知道那五个细节行为。"""

import re
from collections.abc import Mapping

import werkzeug.routing

from apispec import BasePlugin

RE_URL = re.compile(r"<(?:[^:<>]+:)?([^<>]+)>")


def baseconverter2paramschema(converter):
    return {"type": "string"}


def unicodeconverter2paramschema(converter):
    # 朴素:知道是字符串,不知道要从 regex 里抠 minLength/maxLength
    return {"type": "string"}


def integerconverter2paramschema(converter):
    schema = {"type": "integer"}
    if converter.max is not None:
        schema["maximum"] = converter.max
    if converter.min is not None:
        schema["minimum"] = converter.min
    return schema                      # 朴素:不知道 signed


def floatconverter2paramschema(converter):
    schema = {"type": "number"}
    if converter.max is not None:
        schema["maximum"] = converter.max
    if converter.min is not None:
        schema["minimum"] = converter.min
    return schema                      # 朴素:不知道 signed


def anyconverter2paramschema(converter):
    # 朴素:知道有 enum,但不知道要反转义
    return {"type": "string",
            "enum": list(converter.regex[3:-1].split("|"))}


def uuidconverter2paramschema(converter):
    return {"type": "string", "format": "uuid"}


DEFAULT_CONVERTER_MAPPING = {
    werkzeug.routing.BaseConverter: baseconverter2paramschema,
    werkzeug.routing.AnyConverter: anyconverter2paramschema,
    werkzeug.routing.UnicodeConverter: unicodeconverter2paramschema,
    werkzeug.routing.IntegerConverter: integerconverter2paramschema,
    werkzeug.routing.FloatConverter: floatconverter2paramschema,
    werkzeug.routing.UUIDConverter: uuidconverter2paramschema,
}


class FlaskPlugin(BasePlugin):
    """Plugin to create OpenAPI paths from Flask rules"""

    def __init__(self):
        super().__init__()
        self.converter_mapping = dict(DEFAULT_CONVERTER_MAPPING)
        self.openapi_version = None

    def init_spec(self, spec):
        super().init_spec(spec)
        self.openapi_version = spec.openapi_version

    @staticmethod
    def flaskpath2openapi(path):
        return RE_URL.sub(r"{\1}", path)

    def register_converter(self, converter, func):
        self.converter_mapping[converter] = func

    def rule_to_params(self, rule):
        params = []
        # 朴素:用公开的 rule.arguments(集合,无序),不知道 _trace 保序、
        # 也不知道要排除 rule.defaults
        for argument in sorted(rule.arguments):
            param = {"in": "path", "name": argument, "required": True}
            converter = rule._converters[argument]
            for converter_class in type(converter).__mro__:
                if converter_class in self.converter_mapping:
                    func = self.converter_mapping[converter_class]
                    break
            schema = func(converter)
            if self.openapi_version.major < 3:
                param.update(schema)
            else:
                param["schema"] = schema
            params.append(param)
        return params

    def path_helper(self, rule, operations, parameters, **kwargs):
        for path_p in self.rule_to_params(rule):
            p_doc = next(
                (p for p in parameters
                 if isinstance(p, Mapping) and p["in"] == "path"
                 and p["name"] == path_p["name"]), None)
            if p_doc is not None:
                p_doc.update({**path_p, **p_doc})
            else:
                parameters.append(path_p)
        return self.flaskpath2openapi(rule.rule)
