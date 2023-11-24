# ntfsfind

[![LGPLv3+ License](http://img.shields.io/badge/license-LGPLv3+-blue.svg?style=flat)](LICENSE)
[![PyPI version](https://badge.fury.io/py/ntfsfind.svg)](https://badge.fury.io/py/ntfsfind)
[![Python Versions](https://img.shields.io/pypi/pyversions/ntfsfind.svg)](https://pypi.org/project/ntfsfind/)

![ntfsfind](https://gist.githubusercontent.com/sumeshi/c2f430d352ae763273faadf9616a29e5/raw/baa85b045e0043914218cf9c0e1d1722e1e7524b/ntfsfind.svg)

An efficient tool for search files, directories, and alternate data streams directly from NTFS image files.

## Usage

**ntfsfind** can be executed from the command line or incorporated into a Python script.


```bash
$ ntfsfind {{query_regex}} /path/to/imagefile.raw
```

```python
from ntfsfind import ntfsfind

# imagefile_path: str
# search_query: str
# volume_num: Optional[int] = None
# file_type: Literal['raw', 'e01', 'vhd', 'vhdx', 'vmdk'] = 'raw'
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
This tool allows you to search for file, directory, and ADS with regular expression queries.  
Paths are separated by forward slashes (Unix/Linux-style) rather than backslashes (Windows-style).


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
This tool can directly extract and search for $MFT information from image files (RAW, E01, VHD, VHDX, VMDK) containing recorded NTFS volumes as follows.

```.bash
$ ntfsfind '.*\.evtx' /path/to/imagefile.raw
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
When combined with ntfsdump, the retrieved files can be directly dumped from the image file.

```.bash
$ ntfsfind '.*\.evtx' /path/to/imagefile.raw | ntfsdump /path/to/your/imagefile
```

ntfsfind and ntfsdump are compatible if they share the same major and minor versions. For instance, they can be used together if both are version 2.5.x.

https://github.com/sumeshi/ntfsdump


### Options
```
--help, -h:
    Display the help message and exit.

--version, -v:
    Show the program's version number and exit.

--volume-num, -n:
    Specify the NTFS volume number (default is autodetect).

--type, -t:
    Set the image file format (default is raw(dd-format)).
    Supported formats include raw, e01, vhd, vhdx, and vmdk.

--ignore-case, -i:
    Enable case-insensitive search.

--multiprocess, -m:
    Enable multiprocessing for the operation.
```

## Execution Environment
You can run ntfsfind in the following environments:

Windows: Precompiled binaries for Windows are available in the GitHub releases section.

Ubuntu: Precompiled binaries for Linux are also available in the GitHub releases section.

Python: If you prefer to run ntfsfind using Python, it is compatible with Python 3.11 and later versions (3.12 and above). 

Make sure to choose the installation method that best suits your platform and requirements.

## Installation

### from PyPI

```bash
$ pip install ntfsfind
```

### from GitHub Releases
The version compiled into a binary using Nuitka is also available for use.

```bash
$ chmod +x ./ntfsfind
$ ./ntfsfind {{options...}}
```

```bat
> ntfsfind .exe {{options...}}
```

## NTFS File Prerequisites

The image file to be processed must meet the following conditions:

- The file format must be raw, e01, vhd, vhdx, or vmdk.
- It must use the NTFS (NT File System).
- It must have a GUID Partition Table (GPT).

Additional file formats will be added in the future.  
If you have any questions, please feel free to submit an issue.

## Contributing

The source code for ntfsfind is hosted at GitHub, and you may download, fork, and review it from this repository(https://github.com/sumeshi/ntfsfind).  
Please report issues and feature requests. :sushi: :sushi: :sushi:


## License

ntfsfind is released under the [LGPLv3+](https://github.com/sumeshi/ntfsfind/blob/master/LICENSE) License.

Powered by following libraries.
- [pytsk3](https://github.com/py4n6/pytsk)
- [libewf](https://github.com/libyal/libewf)
- [libvhdi](https://github.com/libyal/libvhdi)
- [libvmdk](https://github.com/libyal/libvmdk)
- [pymft-rs](https://github.com/omerbenamram/pymft-rs)
- [Nuitka](https://github.com/Nuitka/Nuitka)
