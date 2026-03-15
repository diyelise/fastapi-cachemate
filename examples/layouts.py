from dataclasses import dataclass
from typing import Annotated

from fastapi import Path, Query
from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    page: int = Field(1, ge=1)
    max_page: int = Field(10, ge=1, le=100)


BlogId = Annotated[int, Field(examples=[1])]
BlogIdPath = Annotated[BlogId, Path(gt=0, le=2147483647, examples=[1])]
BlogSlug = Annotated[str, Field(examples=["best-blog"])]


# Custom simple filter entity for GET route FastAPI
class BlogFilter:
    def __init__(
        self,
        blog_id: BlogId | None = Query(None, description="blog id", alias="id"),
        slug: BlogSlug | None = Query(None, description="blog slug"),
    ):
        self.id = blog_id
        self.slug = slug


# Simple filter based on Dataclass
@dataclass
class BlogDataClassFilter:
    blog_id: int | None = Query(None, description="blog id", alias="id")
    slug: str | None = Query(None, description="blog slug")


# Simple filter based on Pydantic Model
class BlogPydanticFilter(BaseModel):
    blog_id: int | None = Field(None, description="blog id", alias="id")
    slug: str | None = Field(None, description="blog slug")
    page: int = Field(1, ge=1)
    max_page: int = Field(10, ge=1, le=100)
