# Combirepo

Combirepo is a tool for **combi**ning several **repo**sitories into firmware. It is used two build the image in which some packages are taken from one repository and other packages are taken from another. Some packages mean that combirepo is able to detect forward and backward dependencies between RPM packages and installs the package with its dependencies depending on the parameters that user gives to it.

During the run of combirepo the so-called combined repository is generated. After that it is passed as an argument to the usual mic image creator that builds the firmware.

Intended to be used together with OBS-produced repositories.
Refer to `man 1 combirepo` and this guide for details.

## Installation

`combirepo` has several dependencies. On Ubuntu OS, you can install them as follows:
```
sudo apt-get install yum python-igraph python-iniparse zlib1g-dev libxml2-dev mic createrepo python-pip qemu-user-static python-configparser python-all dh-make
```
Use `setup.py` script for building a `deb` package:
```
$ python -m pip install stdeb --user
$ ./setup.py sdist
$ ./setup.py --command-packages=stdeb.command bdist_deb
```
After that it can be installed as follows:
```
$ sudo dpkg -i deb_dist/combirepo_*.deb
```

Another way is to use the Docker build instead:
```
$ ./setup.py sdist
$ docker build -t combirepo ./
$ docker run -Pti combirepo /bin/bash
```

## Terminology

This guide uses specific terminology:

- _Marked_ repository means featured repository, for instance, a repository with packages that are built with [sanitizers](https://github.com/google/sanitizers),
- _non-marked_ repository is an ordinary repository used for the build of production or debugging images.

## Usage

`combirepo` acts as follows:

1. Download repositories.
2. Generate (or re-generate) repository metadata in a proper way.
3. Find kickstart files (with `*.ks` extension) inside the repositories (they are usually contained in the package image-configurations).
4. Build the dependency graphs for packages.
5. Prepare the list of packages based on specified options (forward, backward dependencies, single or excluded packages) that should be taken from marked repository.
6. Create the combined repository, taking marked packages from marked repository and others from the ordinary one.
7. Run the [`mic`](https://github.com/01org/mic) to build the image.

There are two ways to configure `combirepo`:
- `config` file (recommended),
- command line options (not recommended), that are described in manpages (`man 1 combirepo`) and with `--help` message.

If both command line options and config options with the same names are specified, the command line will have the higher priority.

If the `config` file is prepared, you can just run the command:
```
$ combirepo
```
and it will do everything. Also it's possible to set all parameters from command line as follows:
```
combirepo \
    -k my_ks_file.ks \
    -f PACKAGE_NAME \
    -A ARCHITECTURE \
    name-repo /path/to/non/sanitized/repo /path/to/sanitized/repo
```
where `name-repo` is the name of repository as specified in the kickstart file. Such names are given with repo command in kickstart files:
```
repo --name=Tizen-base --baseurl=http://...../tizen-rsa/tizen-2.2.1-vd-4.8/standard/latest/repos/base/armv7l/packages/ --ssl_verify=no
```
Here the `Tizen-base` is this name. In case when the kickstart file contains several repo commands the user should specify a triplet of {`name`, `path to original repository`, `path to marked repository`} for each such command. This usually happens when the image is built from several repositories which are generated from different OBS projects (usually `Base` and `Main/Mobile`). In this case you should specify triplets as follows:
```
combirepo \
    -k my_ks_file.ks \
    -f PACKAGE_NAME \
    -A ARCHITECTURE \
    name-repo1 /path/to/non/sanitized/repo1 /path/to/sanitized/repo1 \
    name-repo2 /path/to/non/sanitized/repo2 /path/to/sanitized/repo2
```

## Marking packages

Here are `combirepo` features that control the set of package that must be marked:

|Feature|Command line option|`config` file option|Description|
|---|:---|:---|:---|
|Mark packages explicitly|`-s --single`|`single_packages`|Explicitly specify the list of packages that should be marked.|
|Greedy marking|`-g --greedy`|`greedy`|Mark as many packages, as possible.|
|Mark forward dependencies|`-f --forward`|`forward_packages`|Mark forward dependencies of marked packages, i.e. those that they depend on.|
|Mark backward dependencies|`-b --backward`|`backward_dependencies`|Mark backward dependencies (a.k.a. dependees) of marked packages, i.e. those that depend on marked packages.|
|Unmark packages|`-e --exclude`|`excluded_packages`|Explicitly exclude packages from marked set.|

## `config` files
Default config file is located in `~/.combirepo.conf`, but it's possible to specify another one with `-c --config` option.
Here is an example of `config` file:
```
# The general section must always present in the config file:
[general]
# The name of profile to be used:
profile = asan317
# Here you can specify any other name you want.
# Usually combirepo stores its cache and temporaries in /var/tmp/combirepo
# directory. You can change this as follows:
# tmp_dir = /my/tmp/dir
 
# The profile usually looks as follows:
[asan317]
# Credentials to the download server:
user = <your user name>
password = <your password, after 1st run it will replaced with encoded one>
 
# 1. Basic parameters:
# The architecture of the image (see option -A in man page):
architecture = armv7l
# First, list the repositories that are contained in the profile:
repos = repo_mobile, repo_base
# Service packages are packages that are additionally installed to the image
# (see option -S in man page):
service_packages = libasan
# Also supplementary repository is specified as the origin of service packages
# (see option -u in man page):
repo_supplementary = http://...../download/live/devel:/2.4:/Mobile:/ASAN/standard/
# Use special kickstart file for the build (see option -k in man page):
# Usually combirepo finds kickstart file in the repository itself, so you need not
# to specify the kickstart name here.
#kickstart = /path/to/tizen-2.4-mobile_20150831.5_mobile_target-TM1.ks
 
# 2. Sanitizing features:
# Forward-sanitized packages (see option -f in man page) a comma separated string:
forward_packages = browser
# Backward-sanitized packages (see option -b in man page) a comma separated string:
backward_packages = efl, libzypp
# Single-sanitized packages (see option -s in man page) a comma separated string:
single_packages = alarm-server
# Packages that are excluded from sanitizing (see option -e in man page) a comma separated string:
excluded_packages = libjpeg, libpng
# Greedy mode, i. e. sanitize all possible packages (see option -g in man page):
# greedy = 1     # [Uncomment this line to enable greedy build]
 
# 3. Additional features:
# Mirror mode, i. e. use packages from original repository if they have been
# added to the sanitized list, but do not present in the marked repository
# (see option -m in man page):
mirror = 1
 
# 4. Resolving of dependency problems:
# Sometimes repositories contain different versions or even different builds of the
# same package. To handle this case you can specify which of them should be used:
# with higher version/release numbers (big) or with lower ones (small)
preferring_strategy = big
# Also some packages can conflict with each other because of erroneous RPM builds,
# and it is needed to specify which of them should be used:
#preferable_packages = coregl coregl-devel taglib gmime camera-interface-sprd-sc7730 heremaps-engine perl perl-x86-arm python cross-armv7l-gcc-accel-x64-armv7l
 
# Repository descriptions:
 
[repo_mobile]
# The name of repository as specified in the kickstart file:
name = 2.4-mobile-target-TM1
# The URL of the original repository:
url_orig = http://...../download/live/Tizen:/2.4:/Mobile/target-TM1/
# The URL of the sanitized repository:
url_marked = http://...../download/live/devel:/2.4:/Mobile:/ASAN:/Mobile/target-TM1/
 
[repo_base]
# The name of repository as specified in the kickstart file:
name = 2.4-base
# The URL of the original repository:
url_orig = http://...../download/live/Tizen:/2.4:/Base/standard/
# The URL of the sanitized repository:
url_marked = http://....../download/live/devel:/2.4:/Mobile:/ASAN:/Base/standard/
```

## License

The application is distributed under GPLv2 license, refer the [LICENSE](LICENSE) file.
