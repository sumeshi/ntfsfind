FROM python:3.9-buster

# install from pypi
WORKDIR /app
RUN pip install ntfsfind

# you can rewrite this command when running the docker container.
# ex. docker run --rm -v $(pwd):/app -t ntfsdump:latest '/$MFT' /app/sample.raw
ENTRYPOINT ["ntfsfind"]
CMD ["-h"]
