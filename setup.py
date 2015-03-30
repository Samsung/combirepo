#!/usr/bin/env python

from setuptools import setup, find_packages

setup(name='combi-repo',
      version='0.1',
      description='Image creation tool from COMBInation of REPOsitories',
      packages=find_packages(),
      install_requires=['argparse',
                        'iniparse',
                        'python-igraph'],
      requires=['yum', 'mic'],
      scripts=['combi-repo.py'])
