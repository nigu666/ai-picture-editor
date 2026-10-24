"""认证、存储、队列与 Provider 配置；不在导入时连接外部服务。"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env", env_file_encoding="utf-8-sig", extra="ignore"
    )

    app_env: Literal["development", "production", "test"] = "development"
    api_port: int = Field(default=7302, ge=1, le=65535)
    database_url: str = Field(repr=False)
    jwt_secret: str = Field(repr=False)
    jwt_ttl_hours: int = Field(default=24, ge=1)

    s3_endpoint: str = "http://127.0.0.1:7313"
    s3_public_endpoint: str = ""
    s3_access_key: str = Field(default="", repr=False)
    s3_secret_key: str = Field(default="", repr=False)
    s3_bucket: str = "retouch"
    s3_url_ttl: int = Field(default=900, ge=1, le=604800)
    image_provider: str = "mock"
    image_model: Literal["wan2.6-t2i"] = "wan2.6-t2i"
    reference_generation_enabled: bool = False
    reference_image_model: Literal["qwen-image-2.0-pro"] = "qwen-image-2.0-pro"
    background_provider: Literal["disabled", "zhipu", "dashscope"] = "disabled"
    background_model: Literal["wan2.6-t2i"] = "wan2.6-t2i"
    outpainting_provider: Literal["disabled", "dashscope"] = "disabled"
    outpainting_model: Literal["wanx2.1-imageedit"] = "wanx2.1-imageedit"
    upscaling_provider: Literal["disabled", "dashscope"] = "disabled"
    upscaling_model: Literal["wanx2.1-imageedit"] = "wanx2.1-imageedit"
    region_provider: Literal["disabled", "dashscope"] = "dashscope"
    region_model: Literal["wanx2.1-imageedit"] = "wanx2.1-imageedit"
    matting_provider: Literal["rembg"] = "rembg"
    matting_model_path: Path = Path.home() / ".rembg/models/u2netp/u2netp.onnx"
    sam_model_dir: Path = Path.home() / ".rembg/models/sam"
    background_repair_backend: Literal["lama", "dashscope"] = "lama"
    lama_model_path: Path = Path.home() / ".rembg/models/lama/lama_fp32.onnx"
    ocr_provider: Literal["none", "rapidocr"] = "none"
    redis_url: str = Field(default="redis://127.0.0.1:7312/0", repr=False)
    queue_name: str = Field(default="ai-picture:queue", min_length=1, max_length=100)
    dashscope_api_key: str = Field(default="", repr=False)
    dashscope_base_url: str = Field(default="https://dashscope.aliyuncs.com", repr=False)
    planner_provider: Literal["dashscope", "zhipu"] = "dashscope"
    zhipu_api_key: str = Field(default="", repr=False)
    zhipu_base_url: str = Field(default="https://open.bigmodel.cn/api/paas/v4", repr=False)
    planner_model: str = Field(default="qwen3.6-flash", min_length=1, max_length=120)
    planner_vision_enabled: bool = True
    planner_timeout_seconds: float = Field(default=20, ge=1, le=120)
    planner_max_tokens: int = Field(default=8192, ge=1024, le=32768)
    planner_reasoning_effort: Literal["low", "high", "max"] = "low"

    @field_validator("dashscope_base_url", "zhipu_base_url")
    @classmethod
    def validate_planner_base_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            not parsed.hostname
            or parsed.scheme not in {"https", "http"}
            or (parsed.scheme == "http" and not local)
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "规划模型地址须为 HTTPS 地址，本机测试可用 HTTP；不接受嵌入凭据或查询参数"
            )
        return value

    @field_validator("jwt_secret")
    @classmethod
    def validate_secret_length(cls, value: str) -> str:
        if len(value.encode("utf-8")) < 32:
            raise ValueError("JWT 密钥至少需要 32 字节")
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
