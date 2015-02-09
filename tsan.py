#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import argparse
import sys
from dependency_graph_builder import DependencyGraphBuilder


def parse_args():
    """
    Parses command-line arguments and builds args structure with which the
    behaviour of the program is controlled.

    @return args structure
    """
    # FIXME: Write a good version string here (with official name and version
    # of the package).
    parser = argparse.ArgumentParser(
        description='Creates a firmware with sanitized packages')

    # FIXME: This argument should be read from config file, not from command
    # line.
    parser.add_argument("repository", type=str,
                        help="Path to repository with non-sanitized packages")

    # FIXME: Ditto.
    parser.add_argument("sanitized_repository", type=str,
                        help="Path to repository with sanitized packages")

    # FIXME: Ditto.
    parser.add_argument("-f", "--forward", type=str, action="append",
                        help="The name of package that should be sanitized "
                        "with all its forward dependencies")

    # FIXME: Ditto.
    parser.add_argument("-b", "--backward", type=str, action="append",
                        help="The name of package that should be sanitized "
                        "with all its backward dependencies (i. e. "
                        "dependees)")

    # FIXME: Ditto.
    parser.add_argument("-s", "--single", type=str, action="append",
                        help="The name of package that should be sanitized")

    # FIXME: Ditto.
    parser.add_argument("-e", "--exclude", type=str, action="append",
                        help="The name of package that should be excluded from"
                        " the final list of sanitized packages.")

    if len(sys.argv) == 1:
        parser.print_help()
        exit(0)
    args = parser.parse_args()
    return args


if __name__ == '__main__':
    args = parse_args()
    dependency_builder = DependencyGraphBuilder()
    repository_graph = dependency_builder.build_graph(args.repository)
