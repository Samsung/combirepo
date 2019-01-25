#!/bin/bash

cd /opt/app/combirepo
git pull origin master
git submodule update
python ./setup.py sdist
python ./setup.py install
