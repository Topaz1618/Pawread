# Pawread

**把一份书单，变成一整套逐章详尽读书笔记。**

贴一份书名列表。Pawread 联网找到每一本书、下载下来、校验拿到的确实是你要的那本、
按章切分，然后让 LLM 逐章读完并写出详尽笔记。每本书一个 Markdown 文件，
带目录，原文引句原样保留。

<!-- 截图放 docs/images/。放好后在这里引用：

![网页界面](docs/images/ui-library.png)
![生成的笔记](docs/images/note-sample.png)

-->

## 快速开始

```bash
git clone https://github.com/Topaz1618/Pawread.git
cd Pawread
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

brew install poppler tesseract        # 文本抽取与 OCR

cp config/env.example config/env.local   # 填 key
```

填 `DASHSCOPE_API_KEY` 给模型，`SMARTPROXY_ACCOUNT` / `SMARTPROXY_PASSWORD`
给代理。网页服务的绑定地址与端口用 `PAWREAD_HOST` 和 `PAWREAD_PORT`。

然后：

```bash
python3 -m pawread.cli --list-file books.txt    # 完整流程
python3 server.py                               # 网页界面
```

笔记写到 `notes/<书名>.md`。

---

## 用法

```bash
python3 -m pawread.cli --help
```

| 参数 | 含义 |
|---|---|
| `--list-file PATH` | 从文件读书名，每行一个 |
| `--builtin-list` | 用 `data/booklist.json` 里的内置清单 |
| `--only N [N ...]` | 只处理指定序号的条目 |
| `--no-discover` | 跳过下载，直接读磁盘上已有的文件 |
| `--no-read` | 到下载与校验为止 |
| `--max-chapters N` | 每本书最多读几章 |
| `--tier NAME` | `test` / `standard` / `quality` / `max` |

```bash
python3 -m pawread.cli --builtin-list --only 6 --only 12
python3 tools/demo_read.py --book "Thinking in Systems" --chapters 3
```

---

## 来源

| 来源 | 合规分级 | 说明 |
|---|---|---|
| `archive.org` | open lending | 主来源。受借阅限制的条目下载不了。 |
| `openlibrary.org` | open lending | 指向 Internet Archive 的扫描件。 |
| `gutenberg.org` | public domain | 版权过期图书。 |
| `donellameadows.org` | publisher | 作者官方发布的《增长的极限》扫描版。 |
| `scottberkun.com` | publisher | 作者官方发布的《Making Things Happen》。 |
| `pacounderhill.com` | publisher | 出版社官方书目页。 |
| `otexts.com` | publisher | 《Forecasting: Principles and Practice》官方站。 |
| `order.poorcharliesalmanack.com` | publisher | 《Poor Charlie's Almanack》官方订购页 —— 不是免费下载。 |
| `books.google.com` | reference | 只有元数据，且限流。默认关闭。 |

---

## 依赖

Python 3.9+、`requests`、`tornado`（仅网页界面需要），以及 poppler 的
`pdftotext` / `pdfinfo` / `pdftoppm`，图像扫描件还需要 `tesseract`。

---

## License

MIT，见 [`LICENSE`](LICENSE)。
