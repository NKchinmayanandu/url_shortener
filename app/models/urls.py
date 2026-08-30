from app.db.base import Base
from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy import func,String
from datetime import datetime
class Url(Base):
    __tablename__ = "urls"
    short_code : Mapped[str] = mapped_column(String(5),primary_key=True)
    original_url : Mapped[str] = mapped_column(nullable=False)
    created_at : Mapped[datetime] = mapped_column(server_default=func.now(),nullable=False)
