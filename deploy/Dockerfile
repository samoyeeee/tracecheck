# TraceCheck on Hugging Face Spaces (Docker SDK). Built from the folder made by
# deploy/build_space.sh. Model keys come from the Space's secrets, never the image.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* && pip install --no-cache-dir uv==0.9.5

# Spaces run the container as uid 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
WORKDIR /home/user/app

# tau2-bench, pinned to the commit every result in this project was produced with
RUN git clone --filter=blob:none https://github.com/sierra-research/tau2-bench.git vendor/tau2-bench \
    && cd vendor/tau2-bench && git checkout -q c06b07dd7c4d4ec61ba6ff9bcdf0b15dd7ef36d4 && uv sync

COPY --chown=user . .

ENV PUBLIC_MODE=1 PORT=7860 AI_DAILY_LIMIT=40 AI_PER_IP_DAILY=3 CHECKS_PER_IP_DAILY=30
EXPOSE 7860
CMD ["vendor/tau2-bench/.venv/bin/python", "-m", "web.serve"]
