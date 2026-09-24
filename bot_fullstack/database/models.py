from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    created: Mapped[DateTime] = mapped_column(DateTime, default=func.now())
    updated: Mapped[DateTime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class Client(Base):
    """Карточка нового клиента.

    Блок `site_*` — поля формы регистрации на сайте (ФИО, пол, e-mail, телефон,
    город, дата рождения, телефон пригласившего). Они приходят с сайта, поэтому
    бот показывает их только для чтения.

    Блок целей и интересов собирается в диалоге и РЕДАКТИРУЕТСЯ человеком:
    на форме сайта этих параметров нет.
    """
    __tablename__ = 'client'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(150), nullable=True)
    registered_at: Mapped[str] = mapped_column(String(40), nullable=True)
    source: Mapped[str] = mapped_column(String(60), nullable=True)
    consent_to_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=True, index=True)

    # --- поля формы регистрации с сайта: только для чтения ---
    site_last_name: Mapped[str] = mapped_column(String(150), nullable=True)
    site_first_name: Mapped[str] = mapped_column(String(150), nullable=True)
    site_middle_name: Mapped[str] = mapped_column(String(150), nullable=True)
    site_gender: Mapped[str] = mapped_column(String(12), nullable=True)
    site_email: Mapped[str] = mapped_column(String(150), nullable=True)
    site_phone: Mapped[str] = mapped_column(String(20), nullable=True, index=True)
    site_city: Mapped[str] = mapped_column(String(150), nullable=True)
    site_birth_date: Mapped[str] = mapped_column(String(10), nullable=True)
    site_referrer_phone: Mapped[str] = mapped_column(String(20), nullable=True)
    site_loaded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- параметры, которые собирает и меняет бот ---
    segment: Mapped[str] = mapped_column(String(16), default='unknown', nullable=False)
    goals: Mapped[str] = mapped_column(String(80), nullable=True)
    interests: Mapped[str] = mapped_column(Text, nullable=True)
    available_time: Mapped[str] = mapped_column(String(160), nullable=True)
    experience: Mapped[str] = mapped_column(String(160), nullable=True)
    flags: Mapped[str] = mapped_column(String(160), nullable=True)
    goal_answer: Mapped[str] = mapped_column(Text, nullable=True)
    clarify_answer: Mapped[str] = mapped_column(Text, nullable=True)
    clarify_attempted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    open_question: Mapped[str] = mapped_column(Text, nullable=True)
    dialogue_step: Mapped[str] = mapped_column(String(24), nullable=True)

    turns: Mapped[list['DialogueTurn']] = relationship(
        back_populates='client', cascade='all, delete-orphan', order_by='DialogueTurn.id'
    )


class DialogueTurn(Base):
    """История диалога и правок: клиент может изменить ответ, история сохраняется."""
    __tablename__ = 'dialogue_turn'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_row_id: Mapped[int] = mapped_column(
        ForeignKey('client.id', ondelete='CASCADE'), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    step: Mapped[str] = mapped_column(String(24), nullable=True)
    answer_ms: Mapped[int] = mapped_column(Integer, nullable=True)

    client: Mapped[Client] = relationship(back_populates='turns')


class Mentor(Base):
    """Наставник, которому передают карточку. Отправка сообщений — только черновиком.

    Наставник опознаётся по номеру телефона (ключ такой же, как у сверки
    клиентов), а telegram_id появляется, когда человек впервые пришлёт номер.
    """
    __tablename__ = 'mentor'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
