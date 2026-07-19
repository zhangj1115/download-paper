# download-paper

一个用于 **下载学术论文 PDF 及其附件/补充材料** 的 AI Agent skill。基于 opencli 训练。

能绕过 `curl` 直接下载失败的常见反爬机制：
- **PMC Proof-of-Work** 反爬挑战
- **出版商 referer / 付费墙**（Elsevier、Cell、Nature、Wiley 等）
- **无开放获取副本的付费文献** → 走 **科研通 (ablesci.com) 文献互助** 兜底
- **开放仓库**（arXiv、bioRxiv、GitHub）直接下载

输入支持：DOI / PMID / 论文标题 / URL。

---

## 安装

### 方式 1：git clone（推荐）

```bash
git clone https://github.com/zhangj1115/download-paper.git ~/.agents/skills/download-paper
```

### 方式 2：手动下载

1. 打开 https://github.com/zhangj1115/download-paper
2. 点绿色 **Code** 按钮 → **Download ZIP**
3. 解压后把文件夹重命名为 `download-paper`，移动到 `~/.agents/skills/` 下

```bash
mkdir -p ~/.agents/skills
mv ~/Downloads/download-paper-main ~/.agents/skills/download-paper
```

### 验证安装

```bash
ls ~/.agents/skills/download-paper/
# 应看到: README.md  SKILL.md  scripts/
```

---

## 使用

安装后，在你的 AI Agent（如 zcode / agently 等支持 skills 的客户端）里直接用自然语言触发即可，例如：

- 「下载这篇文献：10.1038/s41586-024-xxxxx」
- 「把这篇论文及其附件下到 ~/Downloads/papers：PMID 12345678」
- 「download this paper and supplements: https://www.nature.com/articles/...」
- 「用 opencli 登录科研通求助下载这篇 Wiley 的文献」

Agent 会自动识别意图并调用本 skill。

---

## 依赖

- Python 3（运行 `scripts/download_pdf.py`）
- 建议配合支持 skills 的 AI Agent 客户端使用

---

## 卸载

```bash
rm -rf ~/.agents/skills/download-paper
```

---

## 文件结构

```
download-paper/
├── SKILL.md            # skill 主文档（给 AI agent 读的指令）
├── scripts/
│   └── download_pdf.py # PDF 下载脚本
└── README.md           # 本文件
```

## License

MIT