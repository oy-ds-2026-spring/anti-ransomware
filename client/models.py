from typing import Optional
from dataclasses import dataclass, asdict


# requests and responses
@dataclass
class ReadReq:
    filename: str


@dataclass
class WriteReq:
    filename: str
    content: str


@dataclass
class CreateReq:
    filename: str
    content: str = ""


@dataclass
class DeleteReq:
    filename: str


@dataclass
class Response:
    status: Optional[str] = None
    content: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self):
        return {k: v for k, v in asdict(self).items() if v is not None}
