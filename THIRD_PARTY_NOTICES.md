# 第三方组成与来源

本项目本机安装版将独立容器和本地数据模型编排在一起。项目自有代码的授权不覆盖第三方组件；此文不替权利人授予新许可。

| 组成 | 来源及随包材料 |
|---|---|
| MinIO RELEASE.2025-10-15T17-29-55Z | 从未修改的官方源代码编译，AGPL-3.0-only；完整对应源码与许可证在 `third_party/minio/`，构建文件在源码包的 `infrastructure/minio/` |
| U2Netp | [U-2-Net](https://github.com/xuebinqin/U-2-Net)，权重分发来源为 rembg 官方 release；许可证见 `third_party/models/U2Net-LICENSE` |
| SAM vit_b ONNX 量化编码/解码 | [Segment Anything](https://github.com/facebookresearch/segment-anything)，ONNX 权重由 rembg release 分发；许可证见 `third_party/models/SAM-LICENSE` |
| LaMa fp32 ONNX | [Carve/LaMa-ONNX](https://huggingface.co/Carve/LaMa-ONNX)，固定提交和摘要见 `deployment/local/models.json`；模型卡与原 LaMa 许可随包提供 |
| rembg | [danielgatis/rembg](https://github.com/danielgatis/rembg)，许可证在 `third_party/models/rembg-LICENSE` |
| React、Konva 等前端依赖 | 固定解析版本在 `frontend/package-lock.json`；生产依赖列表和许可证副本见 `third_party/frontend-*` |
| Python 与 CV/Agent 依赖 | 固定版本在 `backend/uv.lock`；实际镜像包清单见 `third_party/python-packages.json`，已安装包的许可材料保留于镜像 dist-info 内 |
| PostgreSQL、Redis、Linux 基础层、字体 | 镜像来源和 ID 在 `deployment/local/release.json`；各自包的许可证随镜像保留，使用与再分发应遵循对应上游条款 |

本包不包含 Docker Desktop 安装程序、平台 API 额度或模型服务授权。云服务按用户自己的账号和平台规则使用。

MinIO 上游：[仓库](https://github.com/minio/minio)、[对应源码](https://codeload.github.com/minio/minio/tar.gz/refs/tags/RELEASE.2025-10-15T17-29-55Z)。固定源包 SHA-256：`be6d0bd3696c3a13a35f02d3a0280b64319c67918b4501c5c3d87f96d000085c`。构建步骤为源码包中的 MinIO Dockerfile，无本地修改补丁。
