#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import argparse
import sys
import logging
from sets import Set
import subprocess
from dependency_graph_builder import DependencyGraphBuilder
import temporaries


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


def create_symlink(package_name, location_from, directory_to):
    """
    Creates symlink from file to the file with the same name in the another
    directory.

    @param package          The name of package
    @param location_from    Source of the symlink
    @param directory_to     Destination directory of the symlink
    """
    if not isinstance(location_from, str):
        raise Exception("Location of package {0} is not properly"
                        "set!".format(package_name))
    location_to = os.path.join(directory_to,
                               os.path.basename(location_from))
    os.symlink(location_from, location_to)
    logging.debug("Created symlink from {0} to {1}".format(location_from,
                                                           location_to))


def construct_combined_repository(graph, marked_graph, marked_packages):
    """
    Constructs the temporary repository that consists of symbolic links to
    packages from non-marked and marked repositories.

    @param graph            Dependency graph of the non-marked repository
    @param marked_graph     Dependency graph of the marked repository
    @param marked_packages  Set of marked package names

    @return             The path to the constructed combined repository.
    """
    repository_path = temporaries.create_temporary_directory("combi-repo")
    for package in marked_packages:
        package_id = marked_graph.get_name_id(package)
        if package_id is None:
            raise Exception("Package {0} is not found in marked "
                            "repository".format(package))
        location_from = marked_graph.vs[package_id]["location"]
        create_symlink(package, location_from, repository_path)

    for package in graph.vs["name"]:
        if package in marked_packages:
            continue
        package_id = graph.get_name_id(package)
        location_from = graph.vs[package_id]["location"]
        create_symlink(package, location_from, repository_path)

    if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
        subprocess.call(["ls", "-l", repository_path])

    # Now create the repository with "createrepo" tool:
    subprocess.call(["createrepo", repository_path])

    return repository_path


if __name__ == '__main__':
    args = parse_args()
    if args.arch is None:
        logging.error("Please, specify architecture")
        sys.exit(1)
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    dependency_builder = DependencyGraphBuilder()
    graph, back_graph = dependency_builder.build_graph(args.repository,
                                                       args.arch)
    # Generally speaking, sets of packages in non-marked and marked
    # repositories can differ. That's why we need to build graphs also for
    # marked repository.
    # Nevertheless we assume that graph of marked repository is isomorphic
    # to some subgraph of the non-marked repository graph.
    # FIXME: If it's not true in some pratical cases, then the special
    # treatment is needed.
    marked_graphs = dependency_builder.build_graph(args.marked_repository,
                                                   args.arch)
    marked_graph = marked_graphs[0]

    marked_packages = build_package_set(graph, back_graph, args.forward,
                                        args.backward, args.single,
                                        args.exclude)
    combined_repository_path = construct_combined_repository(graph,
                                                             marked_graph,
                                                             marked_packages)
