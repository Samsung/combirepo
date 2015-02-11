#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import argparse
import sys
import logging
from dependency_graph_builder import DependencyGraphBuilder
from sets import Set


def parse_args():
    """
    Parses command-line arguments and builds args structure with which the
    behaviour of the program is controlled.

    @return args structure
    """
    # FIXME: Write a good version string here (with official name and version
    # of the package).
    parser = argparse.ArgumentParser(
        description='Creates a firmware with marked packages')

    # FIXME: This argument should be read from config file, not from command
    # line.
    parser.add_argument("repository", type=str,
                        help="Path to repository with non-marked packages")

    # FIXME: Ditto.
    parser.add_argument("marked_repository", type=str,
                        help="Path to repository with marked packages")

    # FIXME: Ditto.
    parser.add_argument("-f", "--forward", type=str, action="append",
                        help="The name of package that should be marked "
                        "with all its forward dependencies")

    # FIXME: Ditto.
    parser.add_argument("-b", "--backward", type=str, action="append",
                        help="The name of package that should be marked "
                        "with all its backward dependencies (i. e. "
                        "dependees)")

    # FIXME: Ditto.
    parser.add_argument("-s", "--single", type=str, action="append",
                        help="The name of package that should be marked")

    # FIXME: Ditto.
    parser.add_argument("-e", "--exclude", type=str, action="append",
                        help="The name of package that should be excluded from"
                        " the final list of marked packages.")

    parser.add_argument("-v", "--verbose", action="store_true", dest="verbose",
                        default=False, help="Enable verbose mode")
    parser.add_argument("-A", "--arch", type=str, action="store",
                        help="Specify repo architecture (as for MIC tool)")
    if len(sys.argv) == 1:
        parser.print_help()
        exit(0)
    args = parser.parse_args()
    return args


def build_forward_dependencies(graph, package):
    """
    Builds the set of forward dependencies of the package.

    @param graph        The dependency graph of the repository.
    @param package      The name of package.

    @return             The set of forward dependencies + package itself
    """
    dependencies = Set()
    source = graph.get_name_id(package)
    logging.debug("Found id = {0} for package {1}".format(source, package))
    for vertex in graph.bfsiter(source):
        dependency = graph.vs[vertex.index]["name"]
        logging.debug("Processing vertex {0}, its name is "
                      "{1}".format(vertex.index, dependency))
        dependencies.add(dependency)
    return dependencies


def build_package_set(graph, back_graph, forward, backward, single, exclude):
    """
    Builds the set of marked packages.

    @param graph        The dependency graph of the repository.
    @param back_graph   The backward dependency graph of the repository.
    @param forward      The list of packages marked with their forward
                        dependencies.
    @param backward     The list of packages marked with their backward
                        dependencies.
    @param single       The list of packages marked without dependencies.
    @param exclude      The list of packages excluded from marked packages.

    @return             The set of marked packages.
    """
    marked = Set()
    if isinstance(forward, list):
        for package in forward:
            marked = marked | build_forward_dependencies(graph, package)
    if isinstance(backward, list):
        for package in backward:
            marked = marked | build_forward_dependencies(back_graph, package)
    if isinstance(single, list):
        for package in single:
            marked = marked | Set([package])
    if isinstance(exclude, list):
        for package in exclude:
            marked = marked - Set([package])

    for package in marked:
        logging.debug("Package {0} is marked".format(package))

    return marked


if __name__ == '__main__':
    args = parse_args()
    if args.arch is None:
        logging.error("Please, specify architecture")
        sys.exit(1)
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    dependency_builder = DependencyGraphBuilder()
    (graph, back_graph) = dependency_builder.build_graph(args.repository,
                                                         args.arch)

    packages = build_package_set(graph, back_graph, args.forward,
                                 args.backward, args.single, args.exclude)
