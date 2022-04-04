# ntfsfind

[![MIT License](http://img.shields.io/badge/license-MIT-blue.svg?style=flat)](LICENSE)
[![PyPI version](https://badge.fury.io/py/ntfsfind.svg)](https://badge.fury.io/py/ntfsfind)
[![Python Versions](https://img.shields.io/pypi/pyversions/ntfsfind.svg)](https://pypi.org/project/ntfsfind/)
[![docker build](https://github.com/sumeshi/ntfsdump/actions/workflows/build-docker-image.yaml/badge.svg)](https://github.com/sumeshi/ntfsdump/actions/workflows/build-docker-image.yaml)

![ntfsfind](https://gist.githubusercontent.com/sumeshi/c2f430d352ae763273faadf9616a29e5/raw/baa85b045e0043914218cf9c0e1d1722e1e7524b/ntfsfind.svg)

A tool for search file paths from an NTFS volume on an Image file.

## Usage

```bash
$ ntfsfind {{query_regex}} /path/to/imagefile.raw
```

```python
from ntfsfind import ntfsfind

# imagefile_path: str
# search_query: str
# volume_num: Optional[int] = None
# file_type: Literal['raw', 'e01'] = 'raw'
# multiprocess: bool = False
#
# -> List[str]

records = ntfsfind(
    imagefile_path='./path/to/your/imagefile.raw',
    search_query='.*\.evtx',
    volume_num=2,
    file_type='raw',
    multiprocess=False
)

for record in records:
    print(record)
```


### Query

The query for ntfsfind is a regular expression of the file path to be extracted.
The paths are separated by slashes.

e.g.
```
Original Path: C:\$MFT
Query: '/\$MFT'

# find Eventlogs
Query: '.*\.evtx'

# find Alternate Data Streams
Query: '.*:.*'
```


### Example
Extracts $MFT information directly from image files in raw device mapping format.  
ntfsfind can use regular expressions to search for files.

```.bash
$ ntfsfind '.*\.evtx' /path/to//imagefile.raw
Windows/System32/winevt/Logs/Setup.evtx
Windows/System32/winevt/Logs/Microsoft-Windows-All-User-Install-Agent%4Admin.evtx
Logs/Windows PowerShell.evtx
Logs/Microsoft-Windows-Winlogon%4Operational.evtx
Logs/Microsoft-Windows-WinINet-Config%4ProxyConfigChanged.evtx
Logs/Microsoft-Windows-Windows Firewall With Advanced Security%4ConnectionSecurity.evtx
Logs/Microsoft-Windows-UserPnp%4ActionCenter.evtx
Logs/Microsoft-Windows-TerminalServices-RemoteConnectionManager%4Admin.evtx
Logs/Microsoft-Windows-TerminalServices-LocalSessionManager%4Admin.evtx
Logs/Microsoft-Windows-SMBServer%4Security.evtx
Logs/Microsoft-Windows-SMBServer%4Connectivity.evtx
Logs/Microsoft-Windows-SMBServer%4Audit.evtx
Logs/Microsoft-Windows-SmbClient%4Security.evtx
Logs/Microsoft-Windows-SMBClient%4Operational.evtx
Logs/Microsoft-Windows-Shell-Core%4ActionCenter.evtx
Logs/Microsoft-Windows-SettingSync%4Operational.evtx
...

```


#### When use with [ntfsdump](https://github.com/sumeshi/ntfsdump)

Combined with ntfsdump, the retrieved files can be dumped directly from the image file.

```.bash
$ ntfsfind '.*\.evtx' /path/to/imagefile.raw | ntfsdump /path/to/your/imagefile
```

https://github.com/sumeshi/ntfsdump


### Options
```
--help, -h:
    show help message and exit.

--version, -v:
    show program's version number and exit.

--volume-num, -n:
    NTFS volume number (default: autodetect).

--type, -t:
    image file format (default: raw(dd-format)).
    (raw|e01|vhd|vhdx|vmdk) are supported.

--multiprocess, -m:
    flag to run multiprocessing.
```


## Prerequisites
The image file to be processed must meet the following conditions.

- raw or e01 file format
- NT file system(NTFS)
- GUID partition table(GPT)

Additional file formats will be added in the future.  
If you have any questions, please submit an issue.  


## Installation

### via PyPI

```
$ pip install ntfsfind
```

## Run with Docker
https://hub.docker.com/r/sumeshi/ntfsfind


```bash
$ docker run --rm -v $(pwd):/app -t sumeshi/ntfsfind:latest '/\$MFT' /app/sample.raw
```

## Contributing

The source code for ntfsfind is hosted at GitHub, and you may download, fork, and review it from this repository(https://github.com/sumeshi/ntfsfind).  
Please report issues and feature requests. :sushi: :sushi: :sushi:


## License

ntfsfind is released under the [LGPLv3+](https://github.com/sumeshi/ntfsfind/blob/master/LICENSE) License.

Powered by [pytsk3](https://github.com/py4n6/pytsk), [libewf](https://github.com/libyal/libewf) and [pymft-rs](https://github.com/omerbenamram/pymft-rs).
