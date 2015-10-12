#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Setup related code is placed here"""

from setuptools import setup
from setuptools.command.sdist import sdist
from setuptools.command.install import install
from setuptools.py31compat import get_config_vars
from subprocess import call
from os import path, makedirs
from build_manpage import BuildManPage, check_data_dir
import shlex


class CustomSDistCommand(sdist):
    """Customized sdist - packages rpmrebuild into tarball"""
    def run(self):
        self.run_command('build_manpage')
        print "packing rpmrebuild"
        data_dir = check_data_dir()
        tarball_path = path.join(data_dir, "rpmrebuild.tar")
        cmd = "bash -c 'cd rpmrebuild && \
               git archive --format=tar -o {0} --prefix=rpmrebuild/ \
               HEAD'".format(tarball_path)
        args = shlex.split(cmd)
        call(args)
        sdist.run(self)


class CustomInstallCommand(install):
    """Customized sdist - packages rpmrebuild into tarball"""
    def run(self):
        install.run(self)

        instcmd = self.get_finalized_command('install')
        root = instcmd.root
        prefix = path.abspath(get_config_vars('prefix')[0])
        data_dir = path.abspath(check_data_dir())
        man_file = path.join(data_dir, "combirepo.1")

        if not path.exists(man_file):
            self.run_command('build_manpage')
        man_path = path.abspath('{0}/{1}/share/man/man1/'.format(root, prefix))
        if not path.exists(man_path):
            makedirs(man_path)

        print "Installing man page into {0}".format(man_path)
        cmd = "bash -c 'gzip {0} \
               && install -m 0644 {0}.gz {1}/'".format(man_file, man_path)
        args = shlex.split(cmd)
        call(args)


setup(name='combirepo',
      version='0.1',
      description='Image creation tool from COMBInation of REPOsitories',
      long_description='Combines several repositories into firmware. '
                       'Intended to be used together with OBS-produced '
                       'repositories.',
      author='Ilya Palachev',
      author_email='i.palachev@samsung.com',
      url='https://tizen.org',
      packages=['combirepo'],
      py_modules=['build_manpage'],
      install_requires=['argparse',
                        'iniparse',
                        'python-igraph',
                        'configparser'],
      requires=['yum', 'mic', 'createrepo', 'modifyrepo'],
      package_data={'combirepo': ['data/*']},

      cmdclass={
          'sdist': CustomSDistCommand,
          'build_manpage': BuildManPage,
          'install': CustomInstallCommand,
          },

      entry_points={
          'console_scripts': [
              'combirepo=combirepo.__main__:main'
              ],
          })
