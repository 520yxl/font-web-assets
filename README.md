# 字体管家 Web 字体资源

本仓库保存在线试字使用的完整 WOFF2、字体许可、目录和增量处理记录。
网站仍部署在 EO；浏览器通过 jsDelivr 加载本仓库资源。

## 当前状态

工作流直接读取另一仓库 `520yxl/asfdsfdsgfsdgdsf` 的目录和实际字体文件，不要求重复上传原始字体。
`source-repository.json` 配置来源仓库与分支。每次执行固定源提交，生成 sources.json，再分批转换。
仅处理目录中实际存在的独立字体文件；索引中只有上游下载链接、没有源仓库文件的条目暂不处理。
自动匹配邻近目录的 OFL/Apache/MIT 许可文件；无相邻文件时使用索引内的标准许可声明，并保留原字体内嵌版权、商标、许可及许可链接记录。
未能识别标准许可的项目记录到 source-sync-report.json，后续可补充映射。
许可文本自动识别不等于法律审核，首次发布前仍应核对对应关系。可在脚本中扩展其他许可和目录映射。

## 添加字体

优先由跨仓库同步自动生成清单。若需要单独维护清单，可移除工作流中的 Discover 步骤。
每个字体面/字重使用一个独立 ID。`sources.json` 是对象数组，每个对象包含：

```json
{
  "id": "example-regular",
  "name": "示例字体 Regular",
  "url": "https://raw.githubusercontent.com/OWNER/REPO/40位提交SHA/path/font.ttf",
  "sha256": "源字体文件的64位小写SHA256",
  "source_url": "作者或字体项目页面",
  "license": "实际许可名称",
  "license_url": "https://raw.githubusercontent.com/OWNER/REPO/40位提交SHA/path/LICENSE.txt",
  "license_sha256": "许可文件的64位小写SHA256",
  "weight": 400,
  "style": "normal",
  "approved": true
}
```

示例为字段说明，不是可运行来源。只接受固定 GitHub 提交的公开 raw URL。
支持独立 TTF、OTF、WOFF/WOFF2；TTC/OTC 合集需要先拆分。
可变字体可用 `"weight": "100 900"` 声明范围。

## 运行批次

GitHub → Actions → Convert fonts to WOFF2 → Run workflow，默认每批20个文件。
工作流只接受手动触发，暂未开启定时任务。使用本仓库 GITHUB_TOKEN 写入，无需配置跨仓库密钥。
每批把成功字体和状态提交回 main；下批跳过未变化的成功任务。
单个字体失败继续执行，累计失败3次停止重试。修复来源或删除对应失败状态后可重新处理。
源字体、许可或转换版本变更会重置任务。请勿在任务运行时同时修改 main，推送冲突会失败；修复后重跑。
如果任务超时或取消且尚未提交，该批未提交的进度不会保留，重跑时会重新处理。

转换保留完整字库，校验 Unicode 映射、字形顺序与可变轴。仍需抽样检查实际浏览器效果。
为控制 jsDelivr 资源体积，超过19 MiB的转换结果暂不发布，记录为待分片处理；本版尚未实现分片。
不使用 Git LFS，不主动删除旧资源。撤销 approved 会移除目录项，但不会撤回公开历史和已缓存文件。

## 网站接入

读取 `catalog.json`，将每条记录的 path 拼接到固定提交 CDN 基址：

```text
https://cdn.jsdelivr.net/gh/520yxl/font-web-assets@COMMIT_SHA/
```

目录和字体必须使用同一个已发布提交 SHA。前端用 FontFace 加载 path；weight/style 传给 FontFace 描述参数。
目录没有字体二进制文件，只记录相对路径、哈希、来源及许可路径。
固定提交有利于缓存与回退；新增批次后网站需切换到新提交。EO 不会自动加速外部 CDN 请求。

## 本地执行

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests
python scripts/convert.py --limit 20 --seconds 900
```

转换状态应随字体文件一起提交。脚本和文档未替字体声明统一许可，各字体按其 LICENSE.txt 使用。
