"""容器角色入口：同源API、独立Worker及不连接外部服务的镜像资源检查。"""

import argparse
import asyncio
import json
import logging
import os
import re
import signal
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend/dist"


def image_check(*, require_models=False):
    import importlib
    import shutil

    from PIL import Image

    from app.edits.text import font, font_path
    from app.services.ocr import model_directory

    for name in ("app.main", "app.worker", "cv2", "onnxruntime", "psycopg"):
        importlib.import_module(name)
    assert (FRONTEND / "index.html").is_file() and (FRONTEND / "assets").is_dir()
    assert any((FRONTEND / "assets").glob("*.js"))
    assert font_path().is_file()
    mask = Image.new("L", (300, 60))
    from PIL import ImageDraw

    ImageDraw.Draw(mask).text((0, 0), "中文修图", font=font(28), fill=255)
    assert mask.getbbox() is not None
    model_directory()
    assert os.getuid() != 0
    private_paths = (".env", "backend/.env", "reports", ".local-backups", ".setup-backup")
    assert all(not (FRONTEND.parents[1] / name).exists() for name in private_paths)
    assert shutil.which("node") is None
    if require_models:
        # 仅校验固定权重，不创建推理会话，不自动下载模型。
        from app.services.inpainting import verify_model
        from app.services.matting import verify_model as verify_matting
        from app.services.segmentation import verify_models

        verify_matting(Path(os.environ["MATTING_MODEL_PATH"]))
        verify_models(Path(os.environ["SAM_MODEL_DIR"]))
        verify_model(Path(os.environ["LAMA_MODEL_PATH"]))
    return dict(
        passed=True,
        frontend_present=True,
        backend_imports=True,
        cv_imports=True,
        cjk_font_rendered=True,
        packaged_ocr_models_present=True,
        mounted_models_verified=require_models,
        non_root=(os.getuid() != 0 if hasattr(os, "getuid") else None),
        private_host_files_absent=True,
        node_runtime_absent=True,
        cloud_calls=0,
        database_connected=False,
        task_submitted=False,
    )


async def worker_main():
    from app.config import Settings
    from app.worker import serve

    event = asyncio.Event()
    loop = asyncio.get_running_loop()
    handled = []
    if os.name != "nt":
        for value in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(value, event.set)
            handled.append(value)
    try:
        await serve(Settings(), shutdown_event=event)
    finally:
        for value in handled:
            loop.remove_signal_handler(value)


async def initialize_lab(confirmed, *, local_install=False):
    from urllib.parse import urlsplit

    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from sqlalchemy.engine import make_url

    from app.config import Settings
    from app.db import create_engine
    from app.models import Base
    from app.storage import ObjectStorage

    settings = Settings()
    target = make_url(settings.database_url)
    # 安装版有单独的库、桶和归属标识；保留原教学实验栈的初始化边界。
    marker = "CONTAINER_INSTALL_ID" if local_install else "CONTAINER_LAB_ID"
    expected_database = "ai_picture_local" if local_install else "ai_picture_container_lab"
    expected_bucket = "picture-local" if local_install else "container-lab"
    expected_environment = "development" if local_install else "test"
    if not (
        confirmed
        and re.fullmatch(r"[a-f0-9]{16}", os.environ.get(marker, ""))
        and settings.app_env == expected_environment
        and target.host == "postgres"
        and target.database == expected_database
        and settings.s3_endpoint == "http://minio:9000"
        and settings.s3_bucket == expected_bucket
        and urlsplit(settings.redis_url).hostname == "redis"
    ):
        raise ValueError("仅允许显式初始化对应的独立本机容器环境")
    backend = Path(__file__).resolve().parents[1]

    def migrate(connection):
        config = Config(str(backend / "alembic.ini"))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": True}
        )
        if compare_metadata(context, Base.metadata):
            raise RuntimeError("迁移与当前数据模型不一致")

    engine = create_engine(settings.database_url)
    store = ObjectStorage(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(migrate)
        await store.ensure_bucket()
    finally:
        store.close()
        await engine.dispose()
    return dict(migrated=True, schema_matches=True, storage_bucket_ready=True)


def main():
    parser = argparse.ArgumentParser(description="容器API/Worker入口与镜像资源检查")
    parser.add_argument(
        "role", choices=["api", "worker", "check", "migrate"], nargs="?", default="api"
    )
    parser.add_argument("--require-models", action="store_true")
    parser.add_argument("--initialize-lab", action="store_true")
    parser.add_argument("--initialize-local", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    try:
        if args.role == "check":
            result = image_check(require_models=args.require_models)
            print(json.dumps(result))
        elif args.role == "worker":
            asyncio.run(worker_main())
        elif args.role == "migrate":
            if args.initialize_lab and args.initialize_local:
                raise ValueError("初始化范围不能混用")
            print(json.dumps(asyncio.run(initialize_lab(
                args.initialize_lab or args.initialize_local,
                local_install=args.initialize_local,
            ))))
        else:
            import uvicorn

            from app.config import Settings
            from app.main import create_app

            settings = Settings()
            uvicorn.run(
                create_app(settings, frontend_dir=FRONTEND),
                host="0.0.0.0",
                port=settings.api_port,
                access_log=False,
                log_level="warning",
            )
    except Exception as exc:
        # 配置校验与驱动异常可能携带秘密，不转印原始异常文本。
        print(json.dumps(dict(ok=False, error_type=type(exc).__name__, role=args.role)))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
