# ChatGPT 网页端上传清单

## 推荐方式

创建一个新的 ChatGPT Project，例如 `RepoProof 产品评审`，将下面文件加入
Project Sources，并把 `CHATGPT_WEB_PROJECT_INSTRUCTIONS.md` 的正文粘贴到
Project Instructions。网页端项目不能直接读取本机文件夹；每次关键阶段关闭后
需要重新上传更新过的事实源，除非届时已经连接了包含最新提交的 GitHub 仓库。

## 最小上传包

1. `docs/CHATGPT_WEB_HANDOFF.md`
2. `docs/CHATGPT_WEB_PROJECT_INSTRUCTIONS.md`
3. 主工作树的 `docs/HANDOFF_STATE.md`
4. 主工作树的 `docs/rfc/RFC-011-TOOL-CONTRACT-COHERENCE-AND-RELEASE-STATE.md`
5. 主工作树的 `docs/rfc/RFC-010-LOCAL-TOOL-PRODUCT-CHARTER.md`
6. 主工作树的 `docs/PRODUCT_REDIRECTION.md`
7. 主工作树的 `docs/m4_metrics.json`
8. UI 工作树的 `docs/REPOPROOF_STUDIO_PRODUCT_MODE.md`

## 深度技术评审时追加

- 主工作树的 `README.md`
- 主工作树的 `docs/TOOL_CONTRACT_SCHEMA.md`
- 主工作树的 `docs/TOOL_READY_GATE.md`
- 相关测试文件，优先 `tests/test_tool_release.py`、
  `tests/test_tool_export_upgrade.py`、`tests/ui/test_ui_product_mode.py`
- M5 提交完成后生成的 `git show --stat` 或 PR diff

## 不要上传

- `.env`、API keys、访问令牌、私钥；
- `runs/` 中可能包含用户输入的完整运行目录；
- `~/.repoproof`、本机 release ledger 原件或包含敏感输入的日志；
- 未经检查的压缩包、整个用户主目录或工具缓存；
- 任何你不希望离开本机的真实业务输入。

## 建议首条消息

```text
请先阅读 Project Instructions 和所有 Sources。CHATGPT_WEB_HANDOFF.md 是本次
快照入口，但它同时描述主工作树与独立 UI 工作树。请明确区分：
1) c5c958d 之前已提交的事实；
2) main 上尚未提交的 M5；
3) codex/repoproof-studio-product-mode 上已提交但未合并的 UI。

先复述你理解的最新状态，并指出任何文件冲突或证据缺口；确认后再给建议。
不要假设你可以访问我的本机、未上传文件或未推送提交。
```

## GitHub 连接何时才适合使用

当前 `origin/main` 落后于本地主分支，本地 M5 也尚未提交，因此现在连接
GitHub 不能得到最新项目状态。应至少等到：

1. M5 形成提交；
2. UI 分支完成合并与回归；
3. 用户确认推送；
4. GitHub 上能看到对应提交或 PR。

之后再让网页端 GPT 或 Codex 读取连接仓库/PR，才适合做持续代码级评审。

## OpenAI 官方参考

- ChatGPT Projects 与本地/上传来源：
  https://learn.chatgpt.com/docs/projects
- 网页端使用文件：
  https://learn.chatgpt.com/docs/artifacts-viewer
- GitHub PR 的 Codex 评审流程：
  https://learn.chatgpt.com/docs/third-party/github
