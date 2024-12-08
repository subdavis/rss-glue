FROM python:3.12 AS builder
WORKDIR /opt/rssglue/src

ENV PATH="/opt/rssglue/local/venv/bin:$PATH"
ENV VIRTUAL_ENV="/opt/rssglue/local/venv"

ADD https://install.python-poetry.org /install-poetry.py
RUN POETRY_VERSION=1.8.0 POETRY_HOME=/opt/rssglue/local python /install-poetry.py

COPY . .

RUN poetry env use system
RUN poetry config virtualenvs.create false
RUN poetry install --no-dev
RUN poetry run rss-glue --config /opt/rssglue/src/samples/docker-config.py install

# Distributable Stage
FROM python:3.12
WORKDIR /opt/rssglue/src

ENV PATH="/opt/rssglue/local/venv/bin:$PATH"

COPY --from=builder /opt/rssglue /opt/rssglue

ENTRYPOINT [ "rss-glue" ]