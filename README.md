# ntfsfind

[![LGPLv3+ License](http://img.shields.io/badge/license-LGPLv3+-blue.svg?style=flat)](LICENSE)
[![PyPI version](https://badge.fury.io/py/ntfsfind.svg)](https://badge.fury.io/py/ntfsfind)
[![Python Versions](https://img.shields.io/pypi/pyversions/ntfsfind.svg)](https://pypi.org/project/ntfsfind/)

![ntfsfind logo](https://gist.githubusercontent.com/sumeshi/c2f430d352ae763273faadf9616a29e5/raw/baa85b045e0043914218cf9c0e1d1722e1e7524b/ntfsfind.svg)

An efficient tool for search files, directories, and alternate data streams directly from NTFS image files.

## 🚀 Overview

`ntfsfind` allows digital forensic investigators and incident responders to seamlessly search for records from disk images using regular expressions without needing to mount them. By leveraging powerful backend libraries, it supports reading from standard disk image formats (RAW, E01, VHD(x), VMDK) and reliably parses NTFS structures.

## 📦 Features

- **Direct Search**: Avoid mounting overhead by searching files directly from NTFS partitions.
- **Support Multiple Formats**: Read from `.raw`, `.e01`, `.vhd`, `.vhdx`, and `.vmdk`.
- **Regex Queries**: Find exact files and directories querying with Regular Expressions (partial matching is used by default, similar to `grep`).
- **Alternate Data Stream (ADS)**: Supports finding hidden alternate data streams.
- **Use as a CLI or Python Module**: Highly flexible to integrate into other automated tools.

## ⚙️ Execution Environment

- **Python**: Compatible with Python 3.13+.
- **Precompiled Binaries**: Available for both Windows and Linux in the [GitHub releases](https://github.com/sumeshi/ntfsfind/releases) section.


## 📂 Installation

```bash
# From PyPI
pip install ntfsfind

# Form GitHub Releases (Precompiled Binaries)
chmod +x ./ntfsfind
./ntfsfind --help

# execution via bat on Windows
> ntfsfind.exe --help
```

## 🛠️ Requirements & File Prerequisites

The image file must meet the following conditions:
- **Formats**: `raw`, `e01`, `vhd`, `vhdx`, `vmdk`.
- **File System**: `NTFS`.
- **Partition Table**: `GPT` (MBR will usually be auto-detected, but GPT is officially supported).


## 💻 Usage

### Command Line Interface

You can pass arguments directly into the CLI. Paths are separated by forward slashes (`/`, Unix/Linux-style) rather than backslashes (`\`, Windows-style).

```bash
ntfsfind [OPTIONS] [SEARCH_QUERY] <IMAGE>
```

**Options**:
- `--help`, `-h`: Show help message.
- `--version`, `-V`: Display program version.
- `--volume`, `-n`: Target specific NTFS volume number (default: auto-detects main OS volume).
- `--format`, `-f`: Image file format (default: `raw`). Options: `raw`, `e01`, `vhd`, `vhdx`, `vmdk`.
- `--ignore-case`, `-i`: Enable case-insensitive search.
- `--fixed-strings`, `-F`: Interpret search query as a literal fixed string instead of a regular expression.
- `--multiprocess`, `-m`: Enable multiprocessing for the operation.
- `--out-mft`: Export the parsed `$MFT` raw bytes to the specified file path.

#### Examples

Find Eventlogs:
```bash
$ ntfsfind '.*\.evtx' ./path/to/your/image.raw
/Windows/System32/winevt/Logs/Setup.evtx
/Windows/System32/winevt/Logs/Microsoft-Windows-All-User-Install-Agent%4Admin.evtx
/Logs/Windows PowerShell.evtx
/Logs/Microsoft-Windows-Winlogon%4Operational.evtx
/Logs/Microsoft-Windows-WinINet-Config%4ProxyConfigChanged.evtx
...
```

Find the original $MFT file and files in its path:
```bash
$ ntfsfind '\$MFT' ./path/to/your/image.raw
/$MFT
/$MFTMirr
```

Find Alternate Data Streams:
```bash
$ ntfsfind '.*:.*' ./path/to/your/image.raw
```

Export MFT and search directly from it (faster caching):
```bash
# 1. Export MFT from the image (search query can be omitted)
$ ntfsfind --out-mft /tmp/my_mft.bin ./path/to/your/image.raw

# 2. Later you can query the dumped MFT file instead of the heavy image!
$ ntfsfind -F '.evtx' /tmp/my_mft.bin
```

#### Working with ntfsdump
When combined with [ntfsdump](https://github.com/sumeshi/ntfsdump), the retrieved files can be directly dumped from the image file over standard input (pipe).
`ntfsfind` and `ntfsdump` are compatible if they share the same major and minor versions (e.g. they can be used together if both are version `3.0.x`).
```bash
$ ntfsfind '.*\.evtx' ./path/to/imagefile.raw | ntfsdump ./path/to/your/imagefile
```


### Python Module

You can incorporate `ntfsfind` logic into your own scripts.

```python
from ntfsfind import ntfsfind

# image: str
# search_query: str
# volume: Optional[int] = None
# format: Literal['raw', 'e01', 'vhd', 'vhdx', 'vmdk'] = 'raw'
# multiprocess: bool = False
# ignore_case: bool = False
# fixed_strings: bool = False
# out_mft: Optional[str] = None
#
# -> List[str]

records = ntfsfind(
    image='./path/to/your/imagefile.raw',
    search_query='.*\.evtx',
    volume=2,
    format='raw',
    multiprocess=False,
    ignore_case=True,
    fixed_strings=False,
    out_mft='/tmp/dumped_mft.bin'
)

for record in records:
    print(record)
```


## 🤝 Contributing

We welcome reports, issues, and feature requests. Please do so on the [GitHub repository](https://github.com/sumeshi/ntfsfind). :sushi: :sushi: :sushi:

## 📜 License

Released under the [LGPLv3+](LICENSE) License.

Powered by:
- [pymft-rs](https://github.com/omerbenamram/pymft-rs)
- [pytsk](https://github.com/py4n6/pytsk)
- [libewf](https://github.com/libyal/libewf)
- [libvhdi](https://github.com/libyal/libvhdi)
- [libvmdk](https://github.com/libyal/libvmdk)
- [Nuitka](https://github.com/Nuitka/Nuitka)
