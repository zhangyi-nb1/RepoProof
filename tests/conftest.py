"""套件级防线。

LITELLM_MODE=PRODUCTION:litellm 在 DEV 模式(默认)`import litellm`
时会把 **CWD 的 .env 整个 load_dotenv 进 os.environ**——本仓 .env 存着
真 API key 与 REPOPROOF_* 连接配置。后果有二:(1) 任何在模块层 import
litellm 的测试会把真实连接池漏进所有后续测试的 env(实测:UI 池测试
因此看见 .env 里的 gpt 模型);(2) 秘密静默入环境,违反 Gate 4A
"官方运行只读宿主显式 env"的配置来源纪律。生产侧同一防线钉在
host_guided 的 litellm import 前(setdefault,可被显式覆盖)。
"""

import os

os.environ.setdefault("LITELLM_MODE", "PRODUCTION")
