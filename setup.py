#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup
from setuptools.command.sdist import sdist
from setuptools.command.install import install
from setuptools.py31compat import get_config_vars
from subprocess import call
from os import path
from build_manpage import BuildManPage
import shlex


class CustomSDistCommand(sdist):
    """Customized sdist - packages rpmrebuild into tarball"""
    def run(self):
        self.run_command('build_manpage')
        print "packing rpmrebuild"
        cmd = "bash -c 'cd rpmrebuild && \
               git archive --format=tar -o {0} --prefix=rpmrebuild/ \
               HEAD'".format("../combirepo/data/rpmrebuild.tar")
        args = shlex.split(cmd)
        call(args)
        sdist.run(self)


class CustomInstallCommand(install):
    """Customized sdist - packages rpmrebuild into tarball"""
    def run(self):
        install.run(self)
        prefix = get_config_vars('prefix')[0]
        man_path = '{0}/share/man/man1/'.format(prefix)
        man_file = path.join(path.dirname(path.abspath(__file__)),
                             "combirepo", "data", "combirepo.1")
        if not path.exists(man_file):
            self.run_command('build_manpage')
        print "Installing man page into {0}".format(man_path)
        cmd = "bash -c 'gzip {0} \
               && install -m 0644 {0}.gz {1}'".format(man_file, man_path)
        args = shlex.split(cmd)
        call(args)


setup(name='combirepo',
      version='0.1',
      description='Image creation tool from COMBInation of REPOsitories',
      long_description='Combines several repositories into firmware.'
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
                        'configparser',
                        ],
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
          }
      )
