# ntfsfind

[![MIT License](http://img.shields.io/badge/license-MIT-blue.svg?style=flat)](LICENSE)
[![PyPI version](https://badge.fury.io/py/ntfsfind.svg)](https://badge.fury.io/py/ntfsfind)
[![Python Versions](https://img.shields.io/pypi/pyversions/ntfsfind.svg)](https://pypi.org/project/ntfsfind/)
[![DockerHub Status](https://shields.io/docker/cloud/build/sumeshi/ntfsfind)](https://hub.docker.com/r/sumeshi/ntfsfind)

![ntfsfind](https://gist.githubusercontent.com/sumeshi/c2f430d352ae763273faadf9616a29e5/raw/baa85b045e0043914218cf9c0e1d1722e1e7524b/ntfsfind.svg)

A tool for search file paths from an NTFS volume on a Raw Image file.

## Usage

```bash
$ ntfsfind <query_regex> ./path/to/your/imagefile.raw
```

### Example

```.bash
$ ntfsfind '.*\.evtx' ./path/to/your/imagefile.raw
```

### Options
```
--volume-num, -n: NTFS volume number(default: autodetect).
--multiprocess, -m: flag to run multiprocessing.
```

## Installation

### via PyPI

```
$ pip install ntfsfind
```

## Run with Docker
https://hub.docker.com/r/sumeshi/ntfsfind


```bash
$ docker run -t --rm -v $(pwd):/app/work sumeshi/ntfsfind:latest '/\$MFT' /app/work/sample.raw
```

## Contributing

The source code for ntfsfind is hosted at GitHub, and you may download, fork, and review it from this repository(https://github.com/sumeshi/ntfsfind).  
Please report issues and feature requests. :sushi: :sushi: :sushi:

## License

ntfsfind is released under the [MIT](https://github.com/sumeshi/ntfsfind/blob/master/LICENSE) License.

Powered by [pytsk3](https://github.com/py4n6/pytsk).  
