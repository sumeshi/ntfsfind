# ntfsfind

[![MIT License](http://img.shields.io/badge/license-MIT-blue.svg?style=flat)](LICENSE)
[![PyPI version](https://badge.fury.io/py/ntfsfind.svg)](https://badge.fury.io/py/ntfsfind)
[![Python Versions](https://img.shields.io/pypi/pyversions/ntfsfind.svg)](https://pypi.org/project/ntfsfind/)

![ntfsfind logo](https://gist.githubusercontent.com/sumeshi/c2f430d352ae763273faadf9616a29e5/raw/baa85b045e0043914218cf9c0e1d1722e1e7524b/ntfsfind.svg)

A command-line tool for searching files, directories, and alternate data streams directly from NTFS image files.

## Overview

`ntfsfind` allows digital forensic investigators and incident responders to seamlessly search for records from disk images using regular expressions without needing to mount them. By leveraging powerful backend libraries, it supports reading from standard disk image formats (RAW, E01, VHD(x), VMDK) and reliably parses NTFS structures.

## Features

- **Direct Search**: Avoid mounting overhead by searching files directly from NTFS partitions.
- **Multiple Image Formats**: Read from `RAW`, `E01`, `VHD`, `VHDX`, and `VMDK` images.
- **Regex Queries**: Search file paths with regular expressions. Partial matching is used by default, similar to `grep`.
- **Alternate Data Stream (ADS)**: Supports finding hidden alternate data streams.
- **Use as a CLI or Python Module**: Highly flexible to integrate into other automated tools.

## Execution Environment

- **Python**: Compatible with Python 3.13+.
- **Precompiled Binaries**: Available for both Windows and Linux in the [GitHub releases](https://github.com/sumeshi/ntfsfind/releases) section.


## Installation

```bash
# From PyPI
pip install ntfsfind

# From GitHub Releases (Precompiled Binaries)
chmod +x ./ntfsfind
./ntfsfind --help

# execution via bat on Windows
ntfsfind.exe --help
```

## Supported Input

- Image formats: `RAW`, `E01`, `VHD`, `VHDX`, `VMDK`
- File system: `NTFS`
- Partition tables: `GPT ` is supported; `MBR` may be auto-detected depending on the image


## Usage

### Command Line Interface

You can pass arguments directly into the CLI. Search queries are matched against normalized NTFS paths using forward slashes (`/`).

```bash
ntfsfind [OPTIONS] <IMAGE> [SEARCH_QUERY]
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
$ ntfsfind ./path/to/your/image.raw '.*\.evtx'
/Windows/System32/winevt/Logs/Setup.evtx
/Windows/System32/winevt/Logs/Microsoft-Windows-All-User-Install-Agent%4Admin.evtx
/Logs/Windows PowerShell.evtx
/Logs/Microsoft-Windows-Winlogon%4Operational.evtx
/Logs/Microsoft-Windows-WinINet-Config%4ProxyConfigChanged.evtx
...
```

Find the original $MFT file and files in its path:
```bash
$ ntfsfind ./path/to/your/image.raw '\$MFT'
/$MFT
/$MFTMirr
```

Find Alternate Data Streams:
```bash
$ ntfsfind ./path/to/your/image.raw '.*:.*'
```

Export MFT and search directly from it (faster caching):
A dumped `$MFT` file can also be used as the input image for faster repeated searches.
```bash
# 1. Export MFT from the image (search query can be omitted)
$ ntfsfind --out-mft /tmp/my_mft.bin ./path/to/your/image.raw

# 2. Later you can query the dumped MFT file instead of the heavy image!
$ ntfsfind /tmp/my_mft.bin '.evtx'
```

#### Working with ntfsdump
When combined with [ntfsdump](https://github.com/sumeshi/ntfsdump), the retrieved files can be directly dumped from the image file over standard input (pipe).
`ntfsfind` and `ntfsdump` are compatible if they share the same major and minor versions (e.g. they can be used together if both are version `3.0.x`).

```bash
$ ntfsfind ./path/to/imagefile.raw '.*\.evtx' | ntfsdump -o ./dump ./path/to/imagefile.raw
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
    search_query=r".*\.evtx",
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


## Contributing

We welcome reports, issues, and feature requests. Please do so on the [GitHub repository](https://github.com/sumeshi/ntfsfind). :sushi: :sushi: :sushi:

## License

Released under the [MIT](LICENSE) License.

Powered by:
- [pymft-rs](https://github.com/omerbenamram/pymft-rs)
- [ntfsdump](https://github.com/sumeshi/ntfsdump)
- [Nuitka](https://github.com/Nuitka/Nuitka)

### Third-party licenses

The standalone binaries distributed via GitHub Releases bundle the following third-party libraries.
The libyal libraries (`libewf`, `libvhdi`, `libvmdk`) and `pytsk3` are pulled in transitively via [ntfsdump](https://github.com/sumeshi/ntfsdump), but they are physically bundled inside the ntfsfind binary, so their notices are reproduced here as well.

#### LGPL-3.0-or-later

The following libyal libraries are licensed under the [GNU Lesser General Public License v3.0 or later (LGPL-3.0-or-later)](https://www.gnu.org/licenses/lgpl-3.0.html).
You may obtain, modify, and rebuild them from their upstream sources in accordance with the LGPL.

- [libewf / libewf-python](https://github.com/libyal/libewf)
  - Bundled version: [`libewf-python==20240506`](https://pypi.org/project/libewf-python/20240506/) (source: https://github.com/libyal/libewf/releases/tag/20240506)
  - License text: https://github.com/libyal/libewf/blob/main/COPYING.LESSER
- [libvhdi / libvhdi-python](https://github.com/libyal/libvhdi)
  - Bundled version: [`libvhdi-python==20251119`](https://pypi.org/project/libvhdi-python/20251119/) (source: https://github.com/libyal/libvhdi/releases/tag/20251119)
  - License text: https://github.com/libyal/libvhdi/blob/main/COPYING.LESSER
- [libvmdk / libvmdk-python](https://github.com/libyal/libvmdk)
  - Bundled version: [`libvmdk-python==20240510`](https://pypi.org/project/libvmdk-python/20240510/) (source: https://github.com/libyal/libvmdk/releases/tag/20240510)
  - License text: https://github.com/libyal/libvmdk/blob/main/COPYING.LESSER

#### Apache-2.0

- [pytsk / pytsk3](https://github.com/py4n6/pytsk) — licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).
  - Bundled version: [`pytsk3==20250801`](https://pypi.org/project/pytsk3/20250801/)
  - License text: https://github.com/py4n6/pytsk/blob/master/LICENSE

#### MIT

- [pymft-rs / mft](https://github.com/omerbenamram/pymft-rs) — licensed under the [MIT License](https://opensource.org/licenses/MIT).
  - Bundled version: [`mft==0.7.0`](https://pypi.org/project/mft/0.7.0/)
  - License text: https://github.com/omerbenamram/pymft-rs/blob/master/pyproject.toml
