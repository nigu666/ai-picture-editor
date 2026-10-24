# 本地模型

离线安装版在这里包含 U2Netp、SAM 编码/解码模型和 LaMa ONNX 权重，安装前按 `../models.json` 核对 SHA-256。源码版不含权重，由“从源码构建.cmd”按相同清单准备。

模型以只读目录挂载至容器 `/models`，OCR 模型已经随镜像依赖包含。应用不会因权重缺失而静默下载或替换模型。来源和许可见包根目录 `THIRD_PARTY_NOTICES.md`。
