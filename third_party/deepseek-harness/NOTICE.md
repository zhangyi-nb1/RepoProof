# Third-party NOTICE:DeepSeek Harness

- **项目**:DeepSeek Harness(官方仓 <https://github.com/deepseek-ai/deepseek-harness>)
- **许可**:MIT(License 文本见本目录 `LICENSE`,取自官方仓
  commit `47f943859bef60e4160492346772ded9b24f765a`,
  sha256 `ebb4f09972aee8608be255debaf78451a68e95c290f55c240dec2ecfa16ea6be`)
- **RepoProof 的使用方式**:通过 PyPI 官方发行版把 DSH 作为**不可信
  AgentBackend** 的候选生成 runtime 调用(决策记录
  `docs/adr/ADR-DSH-MINIMAL-AGENT-BACKEND.md`);**不复制其源码进仓**,
  仓内仅保留下列原样引用物。

## 使用的官方工件(全部钉版,封存脚本 `scripts/provision_dsh_runtime.py`)

| 工件 | 版本/来源 | sha256 |
|---|---|---|
| `deepseek-harness-sdk`(PyPI wheel,py3-none-any) | 0.1.0rc6 | `8a05421be4298196cf94383e0a3164b020f5f5977a8d30019cc5add64cb208eb` |
| `deepseek-harness-runtime-bin`(PyPI wheel,macosx_14_0_arm64) | 0.1.0rc6 | `2bbd65edd52dfc340d74f88a890e8031a272a820e58406c2de1f5f5dee51bd9f` |
| 同上(manylinux_2_28_x86_64,本机不装,跨机复现用) | 0.1.0rc6 | `d7261d3bdadfa8d10ab03fd06c6bbc66a182ae27d39892a0eb7c2ce9d63a5448` |
| 同上(manylinux_2_28_aarch64,同上) | 0.1.0rc6 | `99d0ef334a4e3cb178d7b0302bbdd01c8dde6068ee5fe8b01e074541db5c7747` |
| `examples/jsonrpc-agent/minimal.cordis.yml`(minimal 组合) | commit `47f94385…` | `4ddf99b5492fac7b578e3caddb0158815e44d5db176ba0aeab57012d35299fca` |

## SDK 依赖闭包(第三方,非 DeepSeek 项目;pip 实解 + PyPI 官方摘要交叉核验)

| wheel | sha256 |
|---|---|
| `pydantic-2.13.4-py3-none-any.whl`(MIT) | `45a282cde31d808236fd7ea9d919b128653c8b38b393d1c4ab335c62924d9aba` |
| `pydantic_core-2.46.4-cp312-cp312-macosx_11_0_arm64.whl`(MIT) | `962ccbab7b642487b1d8b7df90ef677e03134cf1fd8880bf698649b22a69371f` |
| `annotated_types-0.8.0-py3-none-any.whl`(MIT) | `f072f4d804ea359e4eaf198b1af7a8b0943881a87f31bb764f8bf219bb9419e0` |
| `typing_extensions-4.16.0-py3-none-any.whl`(PSF-2.0) | `481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8` |
| `typing_inspection-0.4.4-py3-none-any.whl`(MIT) | `65b8397ba37ccbce054456aaccddfc91e6e3083c92824df348d96ca832f3f147` |

- 版本与 hash 于 **2026-08-17 对 PyPI JSON API 实核**;
- **composition 未作任何修改**(`patched: false`);若日后确需派生,须换
  composition id 并更新本表;
- PyPI 版本 ↔ 官方 git tag 的映射官方未公示,故钉 **commit** 不钉 tag;
  若后续官方公布对应 tag,补登记,不以未验证 tag 替代 commit;
- 仓内参考副本:`configs/dsh/minimal.upstream.0.1.0rc6.cordis.yml`
  (与封存件钉同一枚 hash,`provision_dsh_runtime.py --verify` 双向核对)。
