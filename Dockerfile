FROM python:3.7-buster

# configure poetry
RUN pip install poetry
RUN poetry config virtualenvs.create false

# install dependencies
WORKDIR /app
COPY . /app
RUN poetry install

# delete caches
RUN rm -rf ~/.cache/pip

# you can rewrite this command when running the docker container.
# ex. docker run -t --rm -v $(pwd):/app/work ntfsfind:latest '/\$MFT' /app/work/sample.raw
ENTRYPOINT ["ntfsfind"]
CMD ["-h"]
