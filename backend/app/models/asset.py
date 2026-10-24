import enum
import uuid

from sqlalchemy import CheckConstraint, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import UUIDBase


class AssetKind(enum.StrEnum):
    ORIGINAL = "original"
    GENERATED = "generated"
    SUBJECT = "subject"
    BACKGROUND = "background"
    MASK = "mask"
    MARKETING = "marketing"
    EXPORT = "export"


class AssetSource(enum.StrEnum):
    UPLOAD = "upload"
    GENERATE = "generate"
    TOOL = "tool"


class Asset(UUIDBase):
    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint("width > 0 AND height > 0", name="ck_assets_dimensions"),
        CheckConstraint("size_bytes > 0", name="ck_assets_size"),
        CheckConstraint(
            "kind IN ('original', 'generated', 'subject', 'background', 'mask', "
            "'marketing', 'export')",
            name="asset_kind",
        ),
        CheckConstraint("source IN ('upload', 'generate', 'tool')", name="asset_source"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[AssetKind] = mapped_column(
        Enum(
            AssetKind,
            values_callable=lambda items: [item.value for item in items],
            native_enum=False,
            create_constraint=False,
            name="asset_kind",
        )
    )
    source: Mapped[AssetSource] = mapped_column(
        Enum(
            AssetSource,
            values_callable=lambda items: [item.value for item in items],
            native_enum=False,
            create_constraint=False,
            name="asset_source",
        )
    )
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    image_format: Mapped[str] = mapped_column(String(8))
    width: Mapped[int]
    height: Mapped[int]
    size_bytes: Mapped[int]
    has_alpha: Mapped[bool]
