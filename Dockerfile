# syntax=docker/dockerfile:1
# Two variants from one file: TORCH=cpu (small, any machine) or TORCH=cuda (NVIDIA GPU,
# needs nvidia-container-toolkit on the host). Per-home files are mounted at /config,
# the Hugging Face model cache at /models — neither is baked into the image.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv

ARG TORCH=cpu
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first (cached layer), then the project itself.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project --extra "$TORCH"

COPY pyproject.toml uv.lock LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --extra "$TORCH"

RUN useradd --uid 1000 --create-home app && mkdir /config /models && chown app:app /config /models
USER app

ENV PATH=/app/.venv/bin:$PATH \
    DECISION_DIR=/config \
    HF_HOME=/models \
    PYTHONUNBUFFERED=1

WORKDIR /config
EXPOSE 8765
# "loading" while the models warm up, "ok" once /decide can answer.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10m --start-interval=5s \
    CMD python -c "import json,urllib.request as u; exit(json.load(u.urlopen('http://127.0.0.1:8765/health'))['status'] != 'ok')"

ENTRYPOINT ["decide"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8765"]
