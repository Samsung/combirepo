# Combirepo

Combirepo is a tool for combining several repositories into firmware.

Intended to be used together with OBS-produced repositories.
Refer `man 1 combirepo` for details.

## Installation

Use either docker build:
```
$ ./setup.py sdist
$ docker build -t combirepo ./
$ docker run -Pti combirepo /bin/bash
```

Or `bdist_deb`:
```
$ python -m pip install stdeb --user
$ ./setup.py sdist
$ ./setup.py --command-packages=stdeb.command bdist_deb
$ sudo dpkg -i deb_dist/combirepo_*.deb
```

## License

The application is distributed under GPLv2 license, refer the LICENSE file.
