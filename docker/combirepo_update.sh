#!/bin/bash

cd /opt/app/combirepo
git pull origin master
python ./setup.py sdist
python ./setup.py install
