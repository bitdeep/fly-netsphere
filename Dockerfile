FROM python:3.10-bookworm@sha256:94c362db08c5b38857943d31b10558ff1856e918605c474d205d72a534929d4e

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MUJOCO_GL=egl \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=graphics,compute,utility \
    TF_CPP_MIN_LOG_LEVEL=2 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libegl1 \
        libgles2 \
        libgl1 \
        libglvnd0 \
        libosmesa6 \
        libglib2.0-0 \
        libgomp1 \
        libx11-6 \
        libxext6 \
        libxrender1 \
        libsm6 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements.lock /app/
RUN pip install --no-cache-dir --only-binary=:all: --require-hashes -r /app/requirements.lock \
    && pip check

ENV PYTHONPATH=/app/flybody
CMD ["bash", "scripts/simulate_city.sh"]
