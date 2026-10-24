"""本机交付版静态页面；只为已知页面返回入口，API与缺失资源保持原语义。"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI, directory: Path):
    directory = directory.resolve()
    index = directory / "index.html"
    if not index.is_file() or not (directory / "assets").is_dir():
        raise RuntimeError("前端交付产物缺失，请先构建交付版")
    app.mount("/assets", StaticFiles(directory=directory / "assets"), name="frontend-assets")

    @app.get("/{page:path}", include_in_schema=False)
    async def frontend_page(page: str):
        # 当前React路由为/auth与/editor；不把未知API或任意文件请求伪装成页面。
        if page.strip("/") not in {"", "auth", "editor"}:
            raise HTTPException(404, "页面或资源不存在")
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-cache"})
