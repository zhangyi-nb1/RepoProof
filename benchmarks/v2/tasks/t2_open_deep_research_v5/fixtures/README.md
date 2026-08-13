# T2 公开 fixtures(agent 可见可用)

- `fake_llm_server.py`:OpenAI 兼容的本地假模型服务(stdlib-only,
  无第三方依赖)。用于满足公开需求"测试必须支持 Fake Model + Fake
  Search / 测试阶段不访问公网"。用法:

```python
from fake_llm_server import start
srv, port = start()                       # 127.0.0.1 随机端口
os.environ["OPENAI_BASE_URL"] = f"http://127.0.0.1:{port}/v1"
os.environ["OPENAI_API_KEY"] = "sk-fake-not-a-real-key"

srv.canary                 # 本次启动现摇的因果金丝雀(见下)
srv.session.final_reports  # 这台服务器发出过的终稿正文
srv.session.requests       # 已收到的 chat/completions 次数
```

- 搭配 ODR 配置 `search_api="none"`(上游自带)即可全离线跑通研究图;
- 该服务对同一主题的响应确定;并发不同主题互不干扰(响应回显主题)。

## 报告溯源的三条判据(对应公开需求 R16)

1. **金丝雀**:每次 `start()` 现摇一枚随机值,写进它返回的**压缩后的研究
   发现**与**终稿正文**(开头结尾各一次)。真的把响应正文接进报告的实现
   必然带着它;在进程内自答一句再套模板的实现带不出来。没有"指定取值"
   的入口 —— 留了那个入口,它就成了可预测的常量。
2. **正文同源**:`srv.session.final_reports` 是本服务器发出过的终稿正文,
   报告里必须找得到其中某一份的开头一段。**这条比金丝雀强** —— 金丝雀
   写在响应正文里,发一发不带 tools 的请求就能把它抠走再贴进自写模板
   (任务工程实测过这条规避路径,当时全绿);正文同源搬不动。比对折叠
   空白后进行,重排版与截断存储不误伤。
3. **调用密度**:走完一次完整研究不止一次模型调用(实测:正控单发作业
   = 11 次 `chat/completions`)。只调一次的装饰性接线在这里暴露。

公开用例 `test_report_body_comes_from_the_engine` 演示了三条的用法。
隐藏验收对第 2 条有更强的同源变体(比对的是本次上游图调用的返回值),
判据同型 —— 诚实实现两边都过。
