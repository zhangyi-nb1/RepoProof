# T2 公开 fixtures(agent 可见可用)

- `fake_llm_server.py`:OpenAI 兼容的本地假模型服务(stdlib-only,
  无第三方依赖)。用于满足公开需求"测试必须支持 Fake Model + Fake
  Search / 测试阶段不访问公网"。用法:

```python
from fake_llm_server import start
srv, port = start()                       # 127.0.0.1 随机端口
os.environ["OPENAI_BASE_URL"] = f"http://127.0.0.1:{port}/v1"
os.environ["OPENAI_API_KEY"] = "sk-fake-not-a-real-key"
```

- 搭配 ODR 配置 `search_api="none"`(上游自带)即可全离线跑通研究图;
- 该服务对同一主题的响应确定;并发不同主题互不干扰(响应回显主题)。
