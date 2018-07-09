#!/usr/bin/env python2
# -*- coding: utf-8 -*-
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#
# Copyright (C) Samsung Electronics, 2016
#
# 2016         Ilya Palachev                 <i.palachev@samsung.com>
#              Vyacheslav Barinov             <v.barinov@samsung.com>

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

        prefix = path.abspath(get_config_vars('prefix')[0])
        data_dir = path.abspath(check_data_dir())
        man_file = path.join(data_dir, "combirepo.1")

        if not path.exists(man_file):
            self.run_command('build_manpage')
        man_path = path.abspath('{0}/share/man/man1/'.format(prefix))
        if not path.exists(man_path):
            makedirs(man_path)

        print "Installing man page into {0}".format(man_path)
        cmd = "bash -c 'gzip -f {0} \
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
      install_requires=['iniparse',
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
