from sqlalchemy import BigInteger, Boolean, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ClientCard(Base):
    """Карточка одна и постоянная на человека: пополняется по ходу диалога."""

    __tablename__ = "client_card"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger)
    display_name: Mapped[str] = mapped_column(String(150), default="")
    segment: Mapped[str] = mapped_column(String(20), default="unknown")
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    card_json: Mapped[str] = mapped_column(Text, default="")
    dialogue_json: Mapped[str] = mapped_column(Text, default="[]")
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[str] = mapped_column(String(32), default="")
