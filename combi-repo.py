#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import shutil
import argparse
import sys
import glob
import logging
import re
from sets import Set
import subprocess
from dependency_graph_builder import DependencyGraphBuilder
import temporaries


def split_names_list(names):
    """
    Splits the given list of names to the list of names, as follows:

    gcc,bash m4
    flex;bison,yacc

    to python list ["gcc", "bash", "m4", "flex", "bison", "yacc"]

    @param names    The list of names

    @return         The splitted list of names
    """
    if names is None:
        return None
    splitted_names = []
    for name in names:
        for splitted_name in re.split("[\,\;\ \n\t]", name):
            splitted_names.append(splitted_name)

    logging.debug("Resulting list after splitting: {0}".format(splitted_names))
    return splitted_names


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
    parser.add_argument("-k", "--kickstart-file", type=str, action="store",
                        dest="kickstart_file", help="Kickstart file used as "
                        "a template")
    parser.add_argument("-o", "--outdir", type=str, action="store",
                        dest="outdir", help="Output directory for MIC.")
    parser.add_argument("-m", "--mirror", action="store_true",
                        dest="mirror", default=False, help="Whether to mirror"
                        " not found marked packages from non-marked "
                        "repository")
    parser.add_argument("-g", "--groups", type=str, action="store",
                        dest="groups", help="group.xml from original "
                        "repository")
    parser.add_argument("-p", "--patterns", type=str, action="store",
                        dest="patterns", help="pattern.xml from original "
                        "repository")
    if len(sys.argv) == 1:
        parser.print_help()
        exit(0)
    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    if args.arch is None:
        logging.error("Please, specify architecture")
        parser.print_help()
        sys.exit(1)

    if args.kickstart_file is None:
        logging.error("Kickstart file is not set!")
        parser.print_help()
        sys.exit(1)

    if args.groups is None:
        logging.error("Please, set path to group.xml")
        parser.print_help()
        sys.exit(1)
    else:
        args.groups = os.path.abspath(args.groups)

    if args.patterns is None:
        logging.error("Please, set path to patterns.xml")
        parser.print_help()
        sys.exit(1)
    else:
        args.patterns = os.path.abspath(args.patterns)

    if args.outdir is None:
        logging.debug("Output directory is not set, so setting it to current "
                      "directory.")
        args.outdir = os.getcwd()
    args.forward = split_names_list(args.forward)
    args.backward = split_names_list(args.backward)
    args.single = split_names_list(args.single)
    args.exclude = split_names_list(args.exclude)

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
        logging.error("location_from = {0}".format(location_from))
        logging.error("Location of package {0} is not properly "
                      "set!".format(package_name))
        """
        raise Exception("Location of package {0} is not properly"
                        "set!".format(package_name))
        """
        return
    location_to = os.path.join(directory_to,
                               os.path.basename(location_from))

    logging.debug("Creating symlink from {0} to {1}".format(location_from,
                                                            location_to))
    os.symlink(location_from, location_to)


def construct_combined_repository(graph, marked_graph, marked_packages,
                                  if_mirror, groups, patterns):
    """
    Constructs the temporary repository that consists of symbolic links to
    packages from non-marked and marked repositories.

    @param graph            Dependency graph of the non-marked repository
    @param marked_graph     Dependency graph of the marked repository
    @param marked_packages  Set of marked package names
    @param if_mirror        Whether to mirror not found marked packages from
                            non-marked repository
    @param groups           Path to group.xml
    @param patterns         Path to patterns.xml

    @return             The path to the constructed combined repository.
    """
    repository_path = temporaries.create_temporary_directory("combi-repo")
    packages_not_found = []
    for package in marked_packages:
        package_id = marked_graph.get_name_id(package)
        if package_id is None:
            packages_not_found.append(package)
            continue
        location_from = marked_graph.vs[package_id]["location"]
        create_symlink(package, location_from, repository_path)

    if len(packages_not_found) != 0:
        for package in packages_not_found:
            logging.error("Marked package {0} not found in marked "
                          "repository".format(package))
        if not if_mirror:
            raise Exception("The above listed packages were not found in "
                            "marked repository")

    packages = Set(graph.vs["name"])
    for package in packages:
        if package in marked_packages:
            continue
        package_id = graph.get_name_id(package)
        location_from = graph.vs[package_id]["location"]
        create_symlink(package, location_from, repository_path)

    if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
        subprocess.call(["ls", "-l", repository_path])

    # Now create the repository with "createrepo" tool:
    repodata_path = os.path.join(repository_path, "repodata")
    os.mkdir(repodata_path)
    groups_local = os.path.join(repodata_path, "group.xml")
    shutil.copy(groups, groups_local)
    patterns_local = os.path.join(repodata_path, "patterns.xml")
    shutil.copy(patterns, patterns_local)
    subprocess.call(["createrepo", repository_path, "-g", "repodata/group.xml",
                    "--database", "--unique-md-filenames"])
    subprocess.call(["modifyrepo", patterns_local, repodata_path])
    initial_directory = os.getcwd()
    os.chdir(repodata_path)
    for group_file in glob.glob("*group.xml"):
        subprocess.call(["modifyrepo", "--remove", group_file, repodata_path])
    os.chdir(initial_directory)

    return repository_path


def create_image(arch, repository_path, kickstart_file_path,
                 output_directory_path):
    """
    Creates an image using MIC tool, from given repository and given kickstart
    file. It creates a copy of kickstart file and replaces "repo" to given
    repository path.

    @param arch                     The architecture of the image
    @param repository_path          The path to the repository
    @param kickstart_file           The kickstart file to be used
    @param output_directory_path    The path to the output directory
    """
    modified_kickstart_file_path = temporaries.create_temporary_file("mod.ks")
    kickstart_file = open(kickstart_file_path, "r")
    modified_kickstart_file = open(modified_kickstart_file_path, "w")

    if_repo_statement_found = False
    for line in kickstart_file:
        if line.startswith("repo "):
            if if_repo_statement_found:
                logging.error("Multiple repo statements found "
                              "in {0}".format(kickstart_file_path))
                continue
            if_repo_statement_found = True
            line = "repo --name=combined_repository"
            line = line + " --baseurl=file://{0}".format(repository_path)
            line = line + " --ssl_verify=no"
        modified_kickstart_file.write(line)
    kickstart_file.close()
    modified_kickstart_file.close()

    # Now create the image using the "mic" tool:
    mic_command = ["sudo", "mic", "create", "loop",
                   modified_kickstart_file_path, "-A", arch, "-o",
                   output_directory_path]
    logging.debug("mic command: {0}".format(mic_command))
    subprocess.call(mic_command)


if __name__ == '__main__':
    args = parse_args()

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
                                                             marked_packages,
                                                             args.mirror,
                                                             args.groups,
                                                             args.patterns)

    create_image(args.arch, combined_repository_path, args.kickstart_file,
                 args.outdir)
