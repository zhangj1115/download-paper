# download-paper

用于下载学术论文正文及补充材料的 Agent skill。输入可为 DOI、PMID、论文标题或 URL；支持单篇和批量处理。

## v0.3 新增

- 单篇文献目录将正文 PDF 放在顶层，补充材料放在 `suppl/`，论文关联代码放在 `code/`。
- 通用批量下载与 CNKI 路线将补充材料保存到 `suppl/`。

## v0.2 新增

- 批量下载与结果清单；可明确选择下载补充材料（`--si`）或只下载正文（`--no-si`）。
- 开放获取、出版商 API、机构图书馆访问和 CNKI 路线；需要登录的路线复用用户已有的浏览器会话。
- 机构与出版商配置工具、数据模板、测试，以及完整的操作说明。

发布记录见 [v0.3](https://github.com/zhangj1115/download-paper/releases/tag/v0.3)、[v0.2](https://github.com/zhangj1115/download-paper/releases/tag/v0.2) 和 [v0.1](https://github.com/zhangj1115/download-paper/releases/tag/v0.1)。

## 安装

```bash
git clone https://github.com/zhangj1115/download-paper.git ~/.agents/skills/download-paper
cd ~/.agents/skills/download-paper
python3 -m pip install -r requirements.txt
```

批量脚本需要 Node.js 22+；Python 辅助脚本需要 Python 3。部分浏览器和文献检索流程还需要可用的 `opencli` 或 CDP 浏览器代理。具体路线与前提见 [SKILL.md](SKILL.md) 和 [机构访问说明](references/institutional-access.md)。

## 使用示例

在支持 skills 的 Agent 中，可直接提出“下载这篇论文及补充材料：DOI ...”。也可以运行：

```bash
node scripts/batch_download.mjs --dois "10.xxxx/example,10.yyyy/example" --si --out ./papers
node scripts/batch_download.mjs --title "论文标题" --no-si --out ./papers
```

`--si` 与 `--no-si` 必须二选一。机构访问或出版商 API 需要先配置，相关命令见 [机构访问说明](references/institutional-access.md)。密钥保存在用户本机的 `~/.config/lit-dl/`，不应提交到仓库。

## 测试

```bash
node --test tests/unit
python3 -m unittest discover -s tests/python -p 'test_*.py'
```

## 目录

- `SKILL.md`：Agent 的完整下载流程。
- `scripts/`：单篇、批量下载及配置脚本。
- `src/`、`data/`：Python 配置逻辑及数据文件。
- `references/`、`examples/`：机构访问说明和清单模板。
- `tests/`：本地测试。

许可证信息见 [LICENSE-nature-downloader](LICENSE-nature-downloader)。
