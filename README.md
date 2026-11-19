# 星知 StarKnows

[starknows.xyz](https://starknows.xyz) 是行业研究报告知识库：按主题、机构和报告年份筛选，搜索全文精读后的智能总结，查看原始 PDF，并继续搜索相关报告。

## 当前内容

截至 2026-11-19，已收录 246 份 PDF，按 SHA256 去重后有 **245 份报告与完整智能总结**。222 份原文可在线查看；23 份超过 Cloudflare 的 25 MiB 单文件上限，保留线上卡片与总结、本地原件。

本次同步第 49、50 批的 16 篇已审核报告。最新 9 篇共 501 个 PDF 物理页，覆盖低轨通信、双十一、办公智能体、中国经济、奥特莱斯、具身智能、冰雪消费、电影市场和电影 AIGC。

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
