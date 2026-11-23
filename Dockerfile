# TraceCheck public server (interactive: import a run, get the diagnosis).
# Deployed on Render's free plan via render.yaml. Model keys come from the
# host's environment settings, never from the image.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* && pip install --no-cache-dir uv==0.9.5

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
WORKDIR /home/user/app

# tau2-bench, pinned to the commit every result in this project was produced with
RUN git clone --filter=blob:none https://github.com/sierra-research/tau2-bench.git vendor/tau2-bench \
    && cd vendor/tau2-bench && git checkout -q c06b07dd7c4d4ec61ba6ff9bcdf0b15dd7ef36d4 && uv sync

# only what the server needs (no run data, no keys)
COPY --chown=user config.yaml ./
COPY --chown=user agent agent
COPY --chown=user runner runner
COPY --chown=user triage triage
COPY --chown=user eval eval
COPY --chown=user web/__init__.py web/serve.py web/limits.py web/
COPY --chown=user web/site web/site
COPY --chown=user results/translations results/translations

ENV PUBLIC_MODE=1 PORT=10000 AI_DAILY_LIMIT=40 AI_PER_IP_DAILY=3 CHECKS_PER_IP_DAILY=30 PYTHONUNBUFFERED=1
EXPOSE 10000
CMD ["vendor/tau2-bench/.venv/bin/python", "-m", "web.serve"]
