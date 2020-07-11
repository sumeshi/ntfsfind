# ntfsfind

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
--volume-num, -n:
    NTFS volume number(default 2, because volume1 is recovery partition).
```

### Required Software
This software requires `The Sleuth Kit`.

https://www.sleuthkit.org/sleuthkit/

```bash
$ brew install sleuthkit
```

## Installation

### via pip

```
$ pip install ntfsfind
```

The source code for ntfsfind is hosted at GitHub, and you may download, fork, and review it from this repository(https://github.com/sumeshi/ntfsfind).

Please report issues and feature requests. :sushi: :sushi: :sushi:

## License

ntfsfind is released under the [MIT](https://github.com/sumeshi/ntfsfind/blob/master/LICENSE) License.

Powered by [The Sleuth Kit](https://www.sleuthkit.org/sleuthkit/).  