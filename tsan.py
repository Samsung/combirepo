#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import argparse
import sys


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Creates a firmware with sanitized packages')
    args = parser.parse_args()
    if len(sys.argv) == 1:
        parser.print_help()
        exit(0)
    parser.parse_args(sys.argv)
