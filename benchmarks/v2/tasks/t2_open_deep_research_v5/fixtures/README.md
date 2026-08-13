# T2 公开 fixtures(agent 可见可用)

- `fake_llm_server.py`:OpenAI 兼容的本地假模型服务(stdlib-only,
  无第三方依赖)。用于满足公开需求"测试必须支持 Fake Model + Fake
  Search / 测试阶段不访问公网"。用法:

```python
from fake_llm_server import start
srv, port = start()                       # 127.0.0.1 随机端口
os.environ["OPENAI_BASE_URL"] = f"http://127.0.0.1:{port}/v1"
os.environ["OPENAI_API_KEY"] = "sk-fake-not-a-real-key"

srv.canary            # 本次启动现摇的因果金丝雀(见下)
srv.session.requests  # 这台服务器已收到的 chat/completions 次数
```

- 搭配 ODR 配置 `search_api="none"`(上游自带)即可全离线跑通研究图;
- 该服务对同一主题的响应确定;并发不同主题互不干扰(响应回显主题)。

## 因果金丝雀(对应公开需求 R16)

每次 `start()` 会现摇一枚随机金丝雀,写进它返回的**压缩后的研究发现**与
**终稿正文**。凡是真的把请求发给本端点、真的把响应正文接进最终报告的
实现,报告里必然带着它;在进程内自答一句再套模板的实现带不出来。

机制就是上面这段话,没有别的;取值每次随机,**没有任何接口可以查**,
也没有"指定取值"的入口 —— 留了那个入口,金丝雀就成了可预测的常量,
也就不再证明任何因果。想拿到它只有一条路:把请求发给它,把响应用起来。

配套判据还有**调用密度**:走完一次完整研究不止一次模型调用(任务工程
实测:正控单发作业 = 11 次 `chat/completions`)。只调一次的装饰性接线
会在这里暴露。公开用例 `test_report_body_comes_from_the_engine` 演示了
两条判据的用法。
