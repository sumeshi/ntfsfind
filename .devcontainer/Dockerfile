FROM python:3.12.0-bullseye

RUN apt -y update && apt upgrade -qqy && apt -y install \
    curl \
    gcc \
    git

RUN pip install -U pip && pip install poetry
