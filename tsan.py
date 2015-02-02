#!/usr/bin/env python2.7
import argparse
import sys


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Creates a firmware with sanitized packages')
    args = parser.parse_args()
    parser.parse_args(sys.argv)
