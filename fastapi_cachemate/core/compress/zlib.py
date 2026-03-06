import functools
import zlib

from fastapi_cachemate.core.decorators.errors import class_error_wrapper, compress_error_handler
from fastapi_cachemate.core.types import CompressManager

zlib_compress = functools.partial(zlib.compress, level=5)


@class_error_wrapper(compress_error_handler)
class ZlibCompressManager(CompressManager):
    def compress(self, data: bytes) -> bytes:
        return zlib_compress(data)

    def decompress(self, data: bytes) -> bytes:
        return zlib.decompress(data)
