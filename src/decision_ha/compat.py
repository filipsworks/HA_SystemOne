"""LM Studio as a local decision server in place of the TypeSafe API.

LM Studio serves the Jev-compatible System One endpoint (POST /v1/systemone, same request and
response as TypeSafe), so the TypeSafe SDK talks to it as is — only the base URL changes.
https://lmstudio.ai/docs/developer/jev-compat/systemone
"""

import os

from typesafe_sdk import TypeSafeClient


def build_lmstudio_client(base_url, transport=None):
    return TypeSafeClient(
        base_url=base_url,
        # The SDK requires a key; LM Studio checks it only with "Require Authentication" on.
        api_key=os.environ.get("LMSTUDIO_API_KEY") or "lm-studio",
        # The SDK zstd-compresses larger bodies when it can (Python 3.14+); LM Studio doesn't document zstd.
        compression=False,
        # The first call may load the model (JIT loading), well past the SDK's 10 s default.
        timeout=120,
        transport=transport,
    )
