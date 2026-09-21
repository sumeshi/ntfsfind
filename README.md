# ntfsfind

[![MIT License](http://img.shields.io/badge/license-MIT-blue.svg?style=flat)](LICENSE)
[![PyPI Version](https://img.shields.io/pypi/v/ntfsfind)](https://pypi.org/project/ntfsfind/)

![ntfsfind logo](https://gist.githubusercontent.com/sumeshi/c2f430d352ae763273faadf9616a29e5/raw/baa85b045e0043914218cf9c0e1d1722e1e7524b/ntfsfind.svg)

A command-line tool for efficiently searching files, directories, and alternate data streams directly from NTFS image files.


## Overview

`ntfsfind` allows digital forensic investigators and incident responders to search NTFS file system records in disk images using regular expressions, without mounting the images.
By leveraging powerful backend libraries, it supports common forensic image formats such as RAW, E01, VHD/VHDX, and VMDK, and reliably parses NTFS structures.
It can also read a VMware VM directory, VMX or VMSD directly, including snapshots and multiple virtual disks, without converting them first.


## Features

- **Direct Search**: Search files directly from NTFS partitions without mounting the image.
- **Multiple Image Formats**: Read `RAW`, `E01`, `VHD`, `VHDX`, and `VMDK` images, and automatically detects the format by signature.
- **VMware Support**: Read a VMware VM directory, VMX or VMSD directly, including snapshots and multiple virtual disks.
- **Regex Queries**: Search file paths with regular expressions. Partial matching is used by default, similar to `grep`.
- **Alternate Data Streams (ADS)**: Find hidden alternate data streams.
- **CLI and Python Module**: Use it from the command line or integrate it into your own automation tools.


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

# On Windows
ntfsfind.exe --help
```


## Supported Input

- Image formats: `RAW`, `E01`, `VHD`, `VHDX`, `VMDK` (auto-detected), plus VMware VM directories, VMX and VMSD.
- File system: `NTFS`.
- Partition tables: `GPT` and `MBR` are both supported.


## Usage

### Command Line Interface

You can pass arguments directly to the CLI. Search queries are matched against normalized NTFS paths using forward slashes (`/`).

```bash
ntfsfind [OPTIONS] <SOURCE> [SEARCH_QUERY]
```

`SOURCE` may be an image file, a VMware VM directory, a VMX or a VMSD:

```text
disk.raw
evidence.E01
disk.vhd
disk.vhdx
disk.vmdk
vm.vmsd
/path/to/vm/
```

**Options**:
- `--help`, `-h`: Show help message.
- `--version`, `-V`: Display program version.
- `--volume`, `-n`: Target specific NTFS volume number (default: auto-detects main OS volume).
- `--image-format`: Force the image format instead of auto-detection. Options: `raw`, `e01`, `vhd`, `vhdx`, `vmdk`.
- `--snapshot`, `-s`: Read the NTFS as it was at the given VMware snapshot UID (see `--list-snapshots`).
- `--disk`, `-d`: Read a specific VMware virtual disk by ID (see `--list-disks`; auto-selected when unique).
- `--list-snapshots`: List VMware snapshots (ID/NAME/CREATED/PARENT) and exit.
- `--list-disks`: List VMware virtual disks (ID/NODE/SIZE/VMDK) and exit.
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

Find alternate data streams:

```bash
$ ntfsfind ./path/to/your/image.raw '.*:.*'
```

Export `$MFT` and search it directly for faster repeated queries:
A dumped `$MFT` file can also be used as input for faster repeated searches.

```bash
# 1. Export MFT from the image (search query can be omitted)
$ ntfsfind --out-mft /tmp/my_mft.bin ./path/to/your/image.raw

# 2. Later you can query the dumped MFT file instead of the heavy image!
$ ntfsfind /tmp/my_mft.bin '.evtx'
```

The image format is auto-detected by signature. Force it with `--image-format` when the signature is not recognizable:

```bash
$ ntfsfind evidence.E01 '.*\.evtx'
$ ntfsfind evidence.bin --image-format raw '.*\.evtx'
```


#### VMware Snapshots and Disks

`ntfsfind` can search a VMware VM directory, VMX or VMSD directly, including a specific snapshot and virtual disk.

List the snapshots and disks first:

```bash
$ ntfsfind ./WindowsVM --list-snapshots
ID  NAME          CREATED              PARENT
1   Initialized   2026-09-01 12:33:43  -
5   NetConnect    2026-09-02 02:25:08  1
6   PrepareTools  2026-09-10 17:46:35  5

$ ntfsfind ./WindowsVM --list-disks
ID  NODE     SIZE     VMDK
0   nvme0:0  100 GiB  Windows10_22H2(x64).vmdk
1   scsi0:1  500 GiB  Data.vmdk
```

Then search the NTFS as it was at a snapshot, optionally selecting a disk:

```bash
# Search snapshot 5 (auto-selects the disk when unique).
$ ntfsfind ./WindowsVM -s 5 '.*\.evtx'

# Search snapshot 5, second virtual disk.
$ ntfsfind ./WindowsVM -s 5 -d 1 '.*\.evtx'
```


#### Working with ntfsdump

When combined with [ntfsdump](https://github.com/sumeshi/ntfsdump), matching files can be dumped directly from the image via standard input.
`ntfsfind` and `ntfsdump` are compatible if they share the same major and minor versions (e.g. they can be used together if both are version `3.2.x`).

```bash
$ ntfsfind ./path/to/imagefile.raw '.*\.evtx' | ntfsdump -o ./dump ./path/to/imagefile.raw
```


### Python Module

You can incorporate `ntfsfind` logic into your own scripts.

```python
from ntfsfind import ntfsfind

# source: Union[str, Path]
# search_query: Optional[str] = None
# volume: Optional[int] = None
# image_format: Optional[str] = None   # None = auto-detect
# snapshot: Optional[str] = None       # VMware snapshot UID
# disk: Optional[int] = None           # VMware virtual disk ID
# multiprocess: bool = False
# ignore_case: bool = False
# fixed_strings: bool = False
# out_mft: Optional[str] = None
# -> List[str]

records = ntfsfind(
    source='./path/to/your/imagefile.raw',
    search_query=r".*\.evtx",
    volume=2,
    image_format=None,
    multiprocess=False,
    ignore_case=True,
    fixed_strings=False,
    out_mft='/tmp/dumped_mft.bin'
)

# VMware VM directory, snapshot and disk selection.
records = ntfsfind(
    source='./WindowsVM',
    search_query=r".*\.evtx",
    snapshot='5',
    disk=1,
)

for record in records:
    print(record)
```


## Contributing

We welcome bug reports, issues, and feature requests. Please do so on the [GitHub repository](https://github.com/sumeshi/ntfsfind). :sushi: :sushi: :sushi:


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
  - Bundled version: [`libvhdi-python==20260901`](https://pypi.org/project/libvhdi-python/20260901/) (source: https://github.com/libyal/libvhdi/releases/tag/20260901)
  - License text: https://github.com/libyal/libvhdi/blob/main/COPYING.LESSER
- [libvmdk / libvmdk-python](https://github.com/libyal/libvmdk)
  - Bundled version: [`libvmdk-python==20260714`](https://pypi.org/project/libvmdk-python/20260714/) (source: https://github.com/libyal/libvmdk/releases/tag/20260714)
  - License text: https://github.com/libyal/libvmdk/blob/main/COPYING.LESSER


#### Apache-2.0

- [pytsk / pytsk3](https://github.com/py4n6/pytsk) — licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).
  - Bundled version: [`pytsk3==20260715`](https://pypi.org/project/pytsk3/20260715/)
  - License text: https://github.com/py4n6/pytsk/blob/master/LICENSE


#### MIT

- [pymft-rs / mft](https://github.com/omerbenamram/pymft-rs) — licensed under the [MIT License](https://opensource.org/licenses/MIT).
  - Bundled version: [`mft==0.7.0`](https://pypi.org/project/mft/0.7.0/)
  - License text: https://github.com/omerbenamram/pymft-rs/blob/master/pyproject.toml
