# 题库数据来源与许可

`banks/` 里的题库文件（`iq-*.json`）是从下列公开数据集中固定抽样得到的题目合集。
**这些题目的版权和许可属于各数据集的作者，不适用本项目代码的 MIT 许可。** 使用或再分发题库文件时，请遵守各数据集自己的许可。

| 题集 | 来源 | 许可 | 作者与论文 |
|---|---|---|---|
| GSM8K | [openai/grade-school-math](https://github.com/openai/grade-school-math) | MIT | Cobbe et al., 2021. *Training Verifiers to Solve Math Word Problems* |
| MMLU | [hendrycks/test](https://github.com/hendrycks/test)（[cais/mmlu](https://huggingface.co/datasets/cais/mmlu)） | MIT | Hendrycks et al., 2021. *Measuring Massive Multitask Language Understanding* |
| MATH-500 | [openai/prm800k](https://github.com/openai/prm800k) 中的 MATH 测试子集（[HuggingFaceH4/MATH-500](https://huggingface.co/datasets/HuggingFaceH4/MATH-500)） | MIT | Hendrycks et al., 2021. *Measuring Mathematical Problem Solving With the MATH Dataset*；Lightman et al., 2023. *Let's Verify Step by Step* |
| ARC-Challenge | [Allen Institute for AI](https://allenai.org/data/arc)（[allenai/ai2_arc](https://huggingface.co/datasets/allenai/ai2_arc)） | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | Clark et al., 2018. *Think you have Solved Question Answering? Try ARC, the AI2 Reasoning Challenge* |
| HellaSwag | [rowanz/hellaswag](https://github.com/rowanz/hellaswag) | MIT | Zellers et al., 2019. *HellaSwag: Can a Machine Really Finish Your Sentence?* |
| C-Eval | [hkust-nlp/ceval](https://github.com/hkust-nlp/ceval)（[ceval/ceval-exam](https://huggingface.co/datasets/ceval/ceval-exam)） | [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)（**禁止商用**） | Huang et al., 2023. *C-Eval: A Multi-Level Multi-Discipline Chinese Evaluation Suite for Foundation Models* |
| 中文指令遵循（`ifeval_zh`） | 本项目编写 | MIT（随代码） | — |

## 对原始数据做了哪些改动

题库只是抽样和格式整理，没有改写题意：

- 每个数据集按固定随机种子抽取一部分题目（每个题库文件的 `manifest` 字段记录了抽样数量和种子）；
- 选项统一整理成 A–D 四项，答案统一成字母（ARC 的数字标号 1–4 换成 A–D，MMLU 的 0–3 换成 A–D）；
- HellaSwag 的题干末尾加了一句中文提示「（选出最合理的后续）」；
- MMLU、C-Eval 的题目记录了所属学科（`sub` 字段）。

依照 CC BY-SA 4.0 与 CC BY-NC-SA 4.0 的「相同方式共享」要求，题库文件中 **ARC-Challenge 部分仍以 CC BY-SA 4.0 提供，
C-Eval 部分仍以 CC BY-NC-SA 4.0 提供（不得用于商业目的）**。

## 本地数据与重新生成

题库文件随仓库提供，能力测试开箱即用、不需要联网。页面上的「更新题集」（或 `python -m llm_bench_pro.bankman build`）
会先把上述数据集的原始数据下载到本地 `data/datasets/`（不入库），再只用本地数据按同样的规则重新抽样生成题库。
默认从魔搭（ModelScope）上这些数据集的国内副本下载；同一份数据无论从哪里下载，生成的题库内容完全相同。
