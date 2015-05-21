#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import shutil
import errno
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


def convert_list_to_sequential_tuples(flat_list, tuple_length):
    """
    Groups a list into consecutive n-tuples, e.g.:
    ([0,3,4,10,2,3], 2) => [(0,3), (4,10), (2,3)]

    Incomplete tuples are discarded, e.g.:
    (range(10), 3) => [(0, 1, 2), (3, 4, 5), (6, 7, 8)]

    @param flat_list    The flat list.
    @param tuple_length The length of generated tuples.

    @return             The list of tuples constructed from original flat
                        list.
    """
    return zip(*[flat_list[i::tuple_length] for i in range(tuple_length)])


def run_parser(parser):
    """
    Runs the constructed parser and performs some additional actions.

    @param parseer  The prepared parser.

    @return         The parsed arguments structure.
    """
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)
    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if len(args.triplets) == 0:
        logging.error("No repository triplet provided!")
        sys.exit(1)
    if len(args.triplets) % 3 != 0:
        logging.error("Number of positional arguments should be devided by "
                      "3")
        sys.exit(1)
    else:
        logging.debug("Triplets before parsing: {0}".format(args.triplets))
        args.triplets = convert_list_to_sequential_tuples(args.triplets, 3)
        logging.debug("Triplets after parsing: {0}".format(args.triplets))

    if args.arch is None:
        logging.error("Please, specify architecture")
        parser.print_help()
        sys.exit(1)

    if args.kickstart_file is None:
        logging.error("Kickstart file is not set!")
        parser.print_help()
        sys.exit(1)

    if args.outdir is None:
        logging.debug("Output directory is not set, so setting it to current "
                      "directory.")
        args.outdir = os.getcwd()

    if args.greedy:
        args.mirror = True
        if (args.forward is not None or args.backward is not None or
                args.single is not None or args.exclude is not None):
            logging.error("Options controlling dependecies are ignored in "
                          "greedy mode!")
            sys.exit(1)

    args.forward = split_names_list(args.forward)
    args.backward = split_names_list(args.backward)
    args.single = split_names_list(args.single)
    args.exclude = split_names_list(args.exclude)

    if args.mic_options is not None:
        splitted_options = []
        for option in args.mic_options:
            splitted_options.extend(re.split("[\ \n\t]", option))
        args.mic_options = splitted_options
    return args


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
    parser.add_argument("triplets", type=str, nargs='+',
                        help="Triplets: 1. Name of "
                        "repository as specified in kickstart file, 2. Path "
                        "to non-marked repository, 3. Path to marked "
                        "repository.")

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
    parser.add_argument("-r", "--regenerate-repodata", action="store_true",
                        default=False, dest="regenerate_repodata",
                        help="Whether to re-generate the "
                        "repodata for specified repositories")
    parser.add_argument("-g", "--greedy", action="store_true",
                        default=False, dest="greedy", help="Greedy mode: get"
                        " as much packages from marked repository as "
                        "possible, and get others from non-marked "
                        "repository.")
    parser.add_argument("-M", "--mic-options", action="append", type=str,
                        dest="mic_options", help="Additional options for MIC.")
    args = run_parser(parser)
    return args


def build_forward_dependencies(graph, package):
    """
    Builds the set of forward dependencies of the package.

    @param graph        The dependency graph of the repository.
    @param package      The name of package.

    @return             The set of forward dependencies + package itself
    """
    source = graph.get_name_id(package)
    logging.debug("Found id = {0} for package {1}".format(source, package))
    if source is None:
        logging.debug("Failed to find package {0} in dependency "
                      "tree.".format(package))
        return Set()
    dependencies = Set()
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
            if not graph.get_name_id(package) is None:
                marked = marked | Set([package])
    if isinstance(exclude, list):
        for package in exclude:
            if not graph.get_name_id(package) is None:
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


def workaround_repodata_open_checksum_bug(repodata_path):
    """
    Workarounds some bug in repodata creation.

    This is a workaround for the case when tag <open-checksum> for group.xml
    is not created in repomd.xml file.

    Nota Bene: This somehow reproduces the standard Tizen repodata creation.
    If you see repodata on release servers, group.xml in them is not
    registered in repomd.xml file, but *.group.xml.gz file is registered in
    it.

    Without this workaround mic will fail during the repodata parsing.

    @param repodata_path  The path to the repodata directory.
    """
    initial_directory = os.getcwd()
    os.chdir(repodata_path)
    backup_group_files = []
    for group_file in glob.glob("*group.xml"):
        backup_group_file = temporaries.create_temporary_file("group.xml")
        shutil.copy(group_file, backup_group_file)
        backup_group_files.append((group_file, backup_group_file))
        exit_value = subprocess.call(["modifyrepo", "--remove", group_file,
                                     repodata_path])
        if exit_value != 0:
            raise Exception("modifyrepo failed with exit value = "
                            "{0}".format(exit_value))

    # Restore backuped group files, but they will not be registered in
    # repomd.xml file anymore.
    for backup_group_file in backup_group_files:
        shutil.copy(backup_group_file[1], backup_group_file[0])

    os.chdir(initial_directory)


def construct_repodata(repository_path, groups, patterns):
    """
    Constructs the repodata in the given repository

    @param repository_path  The path to the repository
    @param groups           Path to group.xml (may be empty)
    @param patterns         Path to patterns.xml (may be empty)
    """
    repository_path = os.path.abspath(repository_path)
    if groups is not None:
        groups = os.path.abspath(groups)
    if patterns is not None:
        patterns = os.path.abspath(patterns)

    repodata_path = os.path.join(repository_path, "repodata")
    if not os.path.isdir(repodata_path):
        os.mkdir(repodata_path)
    createrepo_command = ["createrepo", repository_path, "--database",
                          "--unique-md-filenames"]
    if groups is not None:
        groups_local = os.path.join(repodata_path, "group.xml")
        if groups != groups_local:
            shutil.copy(groups, groups_local)
        createrepo_command.extend(["-g", "repodata/group.xml"])
    logging.debug("createrepo command: \n{0}".format(createrepo_command))
    exit_value = subprocess.call(createrepo_command)
    if exit_value != 0:
        raise Exception("createrepo failed with exit value = "
                        "{0}".format(exit_value))

    if patterns is not None:
        patterns_local = os.path.join(repodata_path, "patterns.xml")
        if patterns != patterns_local:
            shutil.copy(patterns, patterns_local)
        exit_value = subprocess.call(["modifyrepo", patterns_local,
                                     repodata_path])
        if exit_value != 0:
            raise Exception("modifyrepo failed with exit value = "
                            "{0}".format(exit_value))

    workaround_repodata_open_checksum_bug(repodata_path)


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
                            "marked repository.\n"
                            "HINT: use option -m to use non-marked packages "
                            "instead of them.")

    packages = Set(graph.vs["name"])
    for package in packages:
        if package in marked_packages:
            if package not in packages_not_found:
                continue
        package_id = graph.get_name_id(package)
        location_from = graph.vs[package_id]["location"]
        create_symlink(package, location_from, repository_path)

    if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
        subprocess.call(["ls", "-l", repository_path])

    construct_repodata(repository_path, groups, patterns)
    return repository_path


def create_image(arch, repository_names, repository_paths, kickstart_file_path,
                 output_directory_path, mic_options):
    """
    Creates an image using MIC tool, from given repository and given kickstart
    file. It creates a copy of kickstart file and replaces "repo" to given
    repository path.

    @param arch                     The architecture of the image
    @param repository_names         The names of repositorues
    @param repository_paths         The repository paths
    @param kickstart_file           The kickstart file to be used
    @param output_directory_path    The path to the output directory
    @param mic_options              Additional options for MIC.
    """
    modified_kickstart_file_path = temporaries.create_temporary_file("mod.ks")
    kickstart_file = open(kickstart_file_path, "r")
    modified_kickstart_file = open(modified_kickstart_file_path, "w")

    for line in kickstart_file:
        if line.startswith("repo "):
            for i in range(len(repository_names)):
                if " --name={0} ".format(repository_names[i]) in line:
                    path = repository_paths[i]
                    line = re.sub(r'\s+--baseurl=\S+\s+',
                                  r" --baseurl=file://{0} ".format(path),
                                  line)
                    logging.debug("Writting the following line to kickstart "
                                  "file: \n{0}".format(line))
        modified_kickstart_file.write(line)
    kickstart_file.close()
    modified_kickstart_file.close()

    # Now create the image using the "mic" tool:
    mic_command = ["sudo", "mic", "create", "loop",
                   modified_kickstart_file_path, "-A", arch, "-o",
                   output_directory_path, "--tmpfs"]
    if mic_options is not None:
        mic_command.extend(mic_options)
    logging.debug("mic command: {0}".format(mic_command))
    subprocess.call(mic_command)


def find_groups_and_patterns(repository_path):
    """
    Finds the group.xml and patterns.xml in the given repository.

    @param repository_path  The path to the repository

    @return                 Paths to group.xml and patterns.xml
    """
    groups = None
    patterns = None
    for root, dirs, files in os.walk(repository_path):
        for file_name in files:
            if file_name.endswith("group.xml"):
                groups = os.path.join(root, file_name)
            if file_name.endswith("patterns.xml"):
                patterns = os.path.join(root, file_name)
    return groups, patterns


def inform_about_unprovided(provided_symbols, unprovided_symbols,
                            marked_provided_symbols,
                            marked_unprovided_symbols):
    """
    Informs the user when any repository contains symbols that are not provided
    with any of them.

    @param provided_symbols             Symbols provided with non-marked
                                        repository
    @param unprovided_symbols           Symbols unprovided with non-marked
                                        repository
    @param marked_provided_symbols      Symbols provided with marked
                                        repository
    @param marked_unprovided_symbols    Symbols unprovided with marked
                                        repository
    """
    logging.debug("non-marked unprovided symbols: "
                  "{0}".format(unprovided_symbols))
    logging.debug("marked unprovided symbols: "
                  "{0}".format(marked_unprovided_symbols))
    lacking_symbols = unprovided_symbols - marked_provided_symbols
    marked_lacking_symbols = marked_unprovided_symbols - provided_symbols
    common_lacking_symbols = lacking_symbols & marked_lacking_symbols
    lacking_symbols = lacking_symbols - common_lacking_symbols
    marked_lacking_symbols = marked_lacking_symbols - common_lacking_symbols

    for symbol in common_lacking_symbols:
        logging.warning("Some packages in both repositories require symbol"
                        " {0}, but none of them provides it.".format(symbol))
    for symbol in lacking_symbols:
        logging.warning("Some packages in non-marked repository require symbol"
                        " {0}, but none of them provides it.".format(symbol))
    for symbol in marked_lacking_symbols:
        logging.warning("Some packages in marked repository require symbol"
                        " {0}, but none of them provides it.".format(symbol))


def process_repository_triplet(triplet, dependency_builder, args):
    """
    Processes one repository triplet and constructs combined repository for
    it.

    @param triplet              The repository triplet.
    @param dependency_builder   The dependenct graph builder.
    @param args                 Common parsed command-line arguments.

    @return                     Path to combined repository.
    """
    repository_name = triplet[0]
    logging.info("Processing repository \"{0}\"".format(repository_name))
    repository_path = triplet[1]
    if not os.path.isdir(repository_path):
        logging.error("Repository {0} does not "
                      "exist!".format(repository_path))
        sys.exit(1)
    marked_repository_path = triplet[2]
    if not os.path.isdir(marked_repository_path):
        logging.error("Repository {0} does not "
                      "exist!".format(marked_repository_path))
        sys.exit(1)

    graph, back_graph = dependency_builder.build_graph(repository_path,
                                                       args.arch)
    # Generally speaking, sets of packages in non-marked and marked
    # repositories can differ. That's why we need to build graphs also for
    # marked repository.
    # Nevertheless we assume that graph of marked repository is isomorphic
    # to some subgraph of the non-marked repository graph.
    # FIXME: If it's not true in some pratical cases, then the special
    # treatment is needed.
    marked_graphs = dependency_builder.build_graph(marked_repository_path,
                                                   args.arch)
    marked_graph = marked_graphs[0]
    inform_about_unprovided(graph.provided_symbols, graph.unprovided_symbols,
                            marked_graph.provided_symbols,
                            marked_graph.unprovided_symbols)
    if args.greedy:
        marked_packages = Set(marked_graph.vs["name"])
        for package in marked_packages:
            logging.debug("Package {0} is marked".format(package))
        for package in graph.vs["name"]:
            if package not in marked_packages:
                logging.debug("!!! Package {0} is NOT marked "
                              "!!!".format(package))
    else:
        marked_packages = build_package_set(graph, back_graph, args.forward,
                                            args.backward, args.single,
                                            args.exclude)
    groups, patterns = find_groups_and_patterns(repository_path)
    combined_repository_path = construct_combined_repository(graph,
                                                             marked_graph,
                                                             marked_packages,
                                                             args.mirror,
                                                             groups,
                                                             patterns)
    return combined_repository_path, marked_packages


def regenerate_repodata(repository_path):
    """
    Re-generates the repodata for the given repository.

    @param repository_path  The path to the repository.
    """
    groups, patterns = find_groups_and_patterns(repository_path)
    construct_repodata(repository_path, groups, patterns)


def check_command_exists(command):
    """
    Checks whether the command exists in the given PATH evironment and exits
    the program in the case of failure.

    @param command  The command.

    """
    logging.debug("Checking command \"{0}\"".format(command))
    try:
        DEV_NULL = open(os.devnull, 'w')
        subprocess.call([command], stdout=DEV_NULL, stderr=DEV_NULL)
    except OSError as error:
        if error.errno == errno.ENOENT:
            logging.error("\"{0}\" command is not available. Try to "
                          "install it!".format(command))
        else:
            logging.error("Unknown error happened during checking the "
                          "command \"{0}\"!".format(command))
        sys.exit(1)


def check_repository_names(names, kickstart_file_path):
    """
    Checks whether all names specified by user exist in the given kickstart
    file.

    @param names                The list of names specified by user.
    @param kickstart_file_path  The kickstart file.
    """
    try:
        kickstart_file = open(kickstart_file_path, "r")
    except IOError:
        logging.error("Failed to open file {0}".format(kickstart_file_path))
        sys.exit(1)

    possible_names = []
    for line in kickstart_file:
        if line.startswith("repo "):
            possible_names.extend(re.findall(r"--name=(\S+)", line))

    if_error = False
    for name in names:
        if name not in possible_names:
            logging.error("Failed to find repository name "
                          "{0} in kickstart "
                          "file {1} specified "
                          "by user.".format(name, kickstart_file_path))
            logging.error("Possible names are: {0}".format(possible_names))
            if_error = True

    kickstart_file.close()
    if if_error:
        sys.exit(1)


if __name__ == '__main__':
    args = parse_args()

    # These commands will be called in subprocesses, so we need to be sure
    # that they exist in the current environment:
    for command in ["mic", "createrepo", "modifyrepo", "sudo", "ls"]:
        check_command_exists(command)

    # Check that user has given correct arguments for repository names:
    check_repository_names([triplet[0] for triplet in args.triplets],
                           args.kickstart_file)

    if args.regenerate_repodata:
        for triplet in args.triplets:
            regenerate_repodata(triplet[1])
            regenerate_repodata(triplet[2])

    dependency_builder = DependencyGraphBuilder()

    combined_repository_paths = []
    repository_names = []
    marked_packages_total = Set()
    for triplet in args.triplets:
        path, marked_packages = process_repository_triplet(triplet,
                                                           dependency_builder,
                                                           args)
        marked_packages_total = marked_packages_total | marked_packages
        combined_repository_paths.append(path)
        repository_names.append(triplet[0])

    specified_packages = []
    if args.forward is not None:
        specified_packages.extend(args.forward)
    if args.backward is not None:
        specified_packages.extend(args.backward)
    if args.single is not None:
        specified_packages.extend(args.single)
    if args.exclude is not None:
        specified_packages.extend(args.exclude)
    for package in specified_packages:
        if package not in marked_packages_total:
            raise Exception("Failed to find package with name \"{0}\" in any"
                            " of non-marked repositories".format(package))

    create_image(args.arch, repository_names, combined_repository_paths,
                 args.kickstart_file, args.outdir, args.mic_options)
