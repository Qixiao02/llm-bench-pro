# 参与贡献

感谢你愿意改进 LLM Bench Pro！提 Issue 和 Pull Request 都欢迎。

## 提 Issue

- **问题反馈**：写清楚怎么复现（点了哪里、填了什么）、看到了什么、期望是什么；附上运行日志（新建面板里的「复制日志」）和浏览器控制台的报错。
- **功能建议**：说明使用场景，为什么现有功能不够用。
- 请不要在 Issue 里贴 API Key、内网地址或不能公开的测试结果。

## 提交 Pull Request

`main` 分支受保护：**不能直接推送，所有改动都要通过 Pull Request 合并**，并且需要：

1. 维护者（[@Qixiao02](https://github.com/Qixiao02)）审核通过；
2. 自动测试（GitHub Actions）全部通过；
3. PR 里的讨论都已解决。

流程：

```bash
# 1. 在 GitHub 上 Fork 本仓库, 然后克隆你自己的 Fork
git clone https://github.com/<你的用户名>/llm-bench-pro.git
cd llm-bench-pro

# 2. 从 main 新建一个分支
git checkout -b fix/xxx          # 或 feat/xxx、docs/xxx

# 3. 修改、跑测试、提交
python -m unittest discover -s tests
git commit -m "fix(iq): 修正 xxx"

# 4. 推到你的 Fork, 在 GitHub 上向本仓库的 main 发起 Pull Request
git push origin fix/xxx
```

提交信息建议写成 `类型(范围): 说明`，类型用 `feat`（新功能）、`fix`（修问题）、`docs`（文档）、`refactor`、`test`、`chore`；范围如 `perf`、`iq`、`gen`、`ui`、`server`、`bank`。

## 开发环境

- Python 3.8+，**只用标准库，不要引入第三方依赖**；
- Node.js（可选）：装了才会跑前端逻辑测试 `tests/test_frontend.py`；
- 启动：`python run.py 18080`，浏览器打开 <http://127.0.0.1:18080>；
- 测试：`python -m unittest discover -s tests`（测试都用临时数据库和本地模拟服务，不会碰 `data/`，也不联网）。

## 代码约定

- **离线可用**：页面、图表库、字体都在本地，不要加 CDN 或其他外网资源；新增的页面接口要在离线报告里（`app.js` 的 `offlineApi`）有对应处理，否则导出的报告会缺数据。
- **界面默认用大白话，可以一键切成专业词**：默认显示大白话（专业说法在悬停提示和「名词解释」里）；侧栏底部的按钮和各页「更多」菜单里的「切换术语：大白话 / 专业」可以把标签换成 Prefill、TTFT、P95 这样的专业写法。所以新增的名词（指标名、表头、图表标题、坐标轴、图例、结论句里的词）要走统一函数：先在 `app.js` 的 `TERMS` 里加一条（大白话 `name`、专业写法 `pro`、完整说法 `tech`、解释 `desc`），页面上用 `term(key)`，或在文字里写 `{key}` 再交给 `termHtml(...)`（HTML）/ `termText(...)`（图表、CSV、title 等纯文本），不要在调用处手写大白话或专业词。对比统一写成「A 比 B」（A 是正在看的测试，B 是拿来比的）。
- **图表**：统一用 ECharts，不画双纵轴；每张图都能切换成表格查看。
- 界面改动请附亮色和暗色的截图，并在 1440 / 1024 / 390 三种宽度下看一遍。
- 不要提交 `data/` 下的任何内容（数据库、测试结果、作品、下载的题集数据）、API Key 和内网地址。

## 许可

提交到本仓库的代码以 [MIT 许可](LICENSE) 发布。题库数据的来源与许可见 [banks/README.md](banks/README.md)。
