from typing import Any

import orjson
from fastapi.encoders import jsonable_encoder

from fastapi_cachemate.core.decorators.errors import class_error_wrapper, coder_error_handler
from fastapi_cachemate.core.types import CoderManager


@class_error_wrapper(coder_error_handler)
class OrjsonCoderManager(CoderManager):
    def encode(self, data: Any) -> bytes:
        return orjson.dumps(
            data,
            default=jsonable_encoder,
            option=orjson.OPT_NON_STR_KEYS,
        )

    def decode(self, data: bytes) -> Any:
        return orjson.loads(data)
