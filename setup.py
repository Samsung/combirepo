#!/usr/bin/env python

from setuptools import setup, find_packages
from setuptools.command.sdist import sdist
from subprocess import Popen
import shlex


class CustomSDistCommand(sdist):
    """Customized sdist - packages rpmrebuild into tarball"""
    def run(self):
        print "Packing rpmrebuild"
        cmd = "bash -c 'cd rpmrebuild && \
               git archive --format=tar -o ../combirepo/data/rpmrebuild.tar \
               --prefix=rpmrebuild/ HEAD'"
        args = shlex.split(cmd)
        Popen(args)
        sdist.run(self)


setup(name='combirepo',
      version='0.1',
      description='Image creation tool from COMBInation of REPOsitories',
      author='Ilya Palachev',
      author_email='i.palachev@samsung.com',
      packages=['combirepo'],
      install_requires=['argparse',
                        'iniparse',
                        'python-igraph',
                        'configparser',
                        ],
      requires=['yum', 'mic', 'createrepo', 'modifyrepo'],
      package_data={'combirepo': ['data/*']},
      py_modules=['combirepo'],

      cmdclass={
          'sdist': CustomSDistCommand,
          },

      entry_points={
          'console_scripts': [
              'combirepo=combirepo.__main__:main'
              ],
          }
      )
