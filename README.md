# 星知 StarKnows

[starknows.xyz](https://starknows.xyz) 是行业研究报告知识库：按主题、机构和报告年份筛选，搜索全文精读后的智能总结，查看原始 PDF，并继续搜索相关报告。

## 当前内容

截至2026-11-27，已收录260份PDF，按SHA256去重后有 **259份报告与完整智能总结**。236份原文可在线查看；23份超过Cloudflare的25 MiB单文件上限，保留线上卡片与总结、本地原件。

本次同步第52批的5篇已审核报告，共448个PDF物理页，覆盖双11消费趋势、数字文化出海、产业互联网、全球数字文化指数与零售生成式AI。全文阅读后完成人工总结，必要处做本地OCR和原图核对；原文中的统计口径、预测、商业关联及内部矛盾已分别写入总结局限。两篇数字文化报告的样本范围不同，未直接比较或合并总量。

每篇总结包含一句话判断、分条核心结论、带物理页码的主题分析、预测与已发生数据的区分、统计口径与局限、术语注释。资料必须先全文阅读并核对，再通过发布校验；具体要求见 [AGENTS.md](AGENTS.md)。

## 项目结构

- `index.html`：本地单文件应用，嵌入去重报告和已审核总结。
- `cloudflare/`：免费 Workers Static Assets 配置、云端按需加载和浏览器缓存脚本。
- `tools/`：全文提取、本地 OCR、增量入库、总结校验、排序、嵌入与发布工具。
- `reports/inbox/`、`knowledge/`：本地原件、全文、索引和人工审核记录；不纳入此源码仓库。

线上使用静态资源服务，没有后台模型。将 PDF 放入本地文件夹后，需要交给助手完成精读及总结，再更新静态页面。

## 本地更新与部署

完整知识库环境需要 Python 3、Node.js 22+，以及本地原件和审核数据；仅此源码仓库不能重新构建全部报告。

```bash
python3 tools/extract_fulltext.py
# 全文精读、必要 OCR/原图核对，手工完成 review-batch-NN.json
python3 tools/add_reports_incremental.py overrides.json
python3 tools/publish_review_batch.py knowledge/review-batch-NN.json
# 核对并补充 knowledge/report-dates.json
python3 tools/embed_report_library.py
python3 tools/cloudflare_site.py check
python3 tools/cloudflare_site.py deploy
```

构建会核对源文件指纹、发布清单、format 2 总结、页数及排序证据；失败时停止发布。静态资源仅包含页面、总结 JSON 和符合大小要求的 PDF。完整部署说明见 [cloudflare/README.md](cloudflare/README.md)。
