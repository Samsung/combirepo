#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import stat
import shutil
import platform
import errno
import argparse
import sys
import glob
import logging
import re
from sets import Set
import subprocess
import multiprocessing
from dependency_graph_builder import DependencyGraphBuilder
import temporaries
import binfmt


def call_hidden_subprocess(commandline):
    """
    Calls the subprocess and hides all its output.

    @param commandline  The list of command-line words to be executed.

    @return             The return code of the process
    """
    code = 0
    logging.info("Running the command: {0}".format(" ".join(commandline)))
    logging.debug("       in the directory {0}".format(os.getcwd()))
    if logging.getLogger().getEffectiveLevel() <= logging.DEBUG:
        code = subprocess.call(commandline)
    else:
        log_file_name = temporaries.create_temporary_file("process.log")
        with open(log_file_name, 'w') as log_file:
            code = subprocess.call(commandline, stdout=log_file,
                                   stderr=log_file)
        if code != 0:
            logging.error("The subprocess failed!")
            logging.error("STDERR output:")
            with open(log_file_name, 'r') as log_file:
                logging.error("{0}".format(log_file.read()))
    return code


def find_files_fast(directory, expression):
    """
    Finds all files in the given directory that match the given expression.

    @param directory    The directory.
    @param expressiion  The regular expression.
    """
    logging.debug("Searching expression {0} in directory "
                  "{1}".format(expression, directory))
    if not os.path.isdir(directory):
        raise Exception("Directory {0} does not exist!".format(directory))

    matcher = re.compile(expression)
    files_found = []
    for root, dirs, files in os.walk(directory):
        for file_name in files:
            if matcher.match(file_name):
                path = os.path.join(root, file_name)
                path = os.path.abspath(path)
                files_found.append(path)

    return files_found


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
    if args.debug:
        args.verbose = True
        temporaries.debug_mode = True
    if args.verbose:
        logging_level = logging.DEBUG
    else:
        logging_level = logging.INFO

    if args.log_file_name:
        logging.basicConfig(level=logging_level, filename=args.log_file_name)
    else:
        logging.basicConfig(level=logging_level)

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

    if args.preferables is None:
        args.preferables = []
    if args.preferring_strategy is not None:
        if args.preferring_strategy not in ["small", "big"]:
            logging.error("Unknown preferring strategy: "
                          "{0}".format(args.preferring_strategy))
            sys.exit("Error.")
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

    parser.add_argument("-S", "--specific-package", type=str, action="append",
                        dest="specific_packages", default=["libasan"],
                        help="The name of package that is not installed to "
                        "the image by default, but that must be installed in "
                        "this build.")

    parser.add_argument("-v", "--verbose", action="store_true", dest="verbose",
                        default=False, help="Enable verbose mode")
    parser.add_argument("-d", "--debug", action="store_true", dest="debug",
                        default=False, help="Enable debug mode (temporaries "
                        "will be saved)")
    parser.add_argument("-l", "--logfile", type=str, action="store",
                        dest="log_file_name", help="Log all output to the "
                        "given file.")
    parser.add_argument("-A", "--arch", type=str, action="store",
                        help="Specify repo architecture (as for MIC tool)")
    parser.add_argument("-k", "--kickstart-file", type=str, action="store",
                        dest="kickstart_file", help="Kickstart file used as "
                        "a template")
    parser.add_argument("-o", "--outdir", type=str, action="store",
                        dest="outdir", help="Output directory for MIC.")
    parser.add_argument("-O", "--outdir-original", type=str, action="store",
                        dest="outdir_original", help="Output directory for "
                        "MIC (during the original repository building)")
    parser.add_argument("-i", "--original-image", type=str, action="store",
                        dest="original_image", help="Don't build original "
                        "image, use the specified one for that. Given "
                        "argument must be the path to image or images "
                        "directory.")
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
                        dest="mic_options", help="Additional options for MIC."
                        "\nBy default the following options are set:"
                        "\n \"sudo mic create loop <YOUR KICKSTART FILE> "
                        "\n -A <THE SPECIFIED ARCHITECTURE> "
                        "\n -o <THE SPECIFIED OUTPUT DIRECTORY>"
                        "\n --tmpfs \n --pkgmgr=zypp \n --shrink\""
                        "\n     . You can append options to add new or change "
                        "old ones.")
    parser.add_argument("-p", "--prefer", action="append", type=str,
                        dest="preferables", help="Package names that should "
                        "be prefered in case of \"have choice\" problem.")
    parser.add_argument("-P", "--preferring-strategy", action="store",
                        type=str, dest="preferring_strategy",
                        help="Have choice "
                        "resolving strategy for the case when there are "
                        "packages with equal names but different "
                        "versions/build numbers. Possible values: "
                        "small (prefer smaller), "
                        "big (prefer bigger).")
    parser.add_argument("-q", "--qemu", action="store", type=str,
                        dest="qemu_path", help="Path to qemu that should be "
                        "used. You can specify the path either to RPM "
                        "package with qemu or to the working qemu executable "
                        "itself")
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


def build_package_set(graph, back_graph, forward, backward, single, exclude,
                      specific):
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
    if isinstance(specific, list):
        for package in specific:
            if not graph.get_name_id(package) is None:
                marked = marked | Set([package])

    for package in marked:
        logging.info("Package {0} is marked".format(package))

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
        sys.exit("Error.")
    if not os.path.isfile(location_from):
        logging.error("File {0} does not exist!".format(location_from))
        sys.exit("Error.")

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
        exit_value = call_hidden_subprocess(["modifyrepo", "--remove",
                                            group_file, repodata_path])
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
    exit_value = call_hidden_subprocess(createrepo_command)
    if exit_value != 0:
        raise Exception("createrepo failed with exit value = "
                        "{0}".format(exit_value))

    if patterns is not None:
        patterns_local = os.path.join(repodata_path, "patterns.xml")
        if patterns != patterns_local:
            shutil.copy(patterns, patterns_local)
        exit_value = call_hidden_subprocess(["modifyrepo", patterns_local,
                                            repodata_path])
        if exit_value != 0:
            raise Exception("modifyrepo failed with exit value = "
                            "{0}".format(exit_value))

    workaround_repodata_open_checksum_bug(repodata_path)


def create_patched_package(queue, package_name, release, patching_root):
    """
    Patches the given package using rpmrebuild and the patching root.

    @param queue            The queue used for saving the resulting file name.
    @param package_name     The basename of the package.
    @param release          The release number of the corresponding non-marked
                            package.
    @param patching_root    The root used for RPM patching.
    """
    logging.debug("Chrooting to the directory {0}".format(patching_root))
    os.chroot(patching_root)
    os.chdir("/")
    if not os.path.isfile(package_name):
        logging.error("Package {0} is not found in patching "
                      "root.".format(package_name))
        sys.exit("Error.")

    repmrebuild_command = ["rpmrebuild",
                           "--release={0}".format(release), "-p", "-n",
                           package_name]
    logging.info("Running command: {0}".format(" ".join(repmrebuild_command)))
    log_file_name = temporaries.create_temporary_file("rpmrebuild.log")
    with open(log_file_name, 'w') as log_file:
        code = subprocess.call(repmrebuild_command, stdout=log_file,
                               stderr=log_file)
    if code != 0:
        logging.error("The subprocess failed!")
        logging.error("STDERR output:")
        with open(log_file_name, 'r') as log_file:
            logging.error("{0}".format(log_file.read()))

    result = None
    with open(log_file_name, 'r') as log_file:
        for line in log_file:
            if line.startswith("result: "):
                result = line.replace("result: ", "")
                result = result.replace("\n", "")
    if result is None:
        logging.error("Failed to patch RPM file!")
        sys.exit("Error.")
    queue.put(result)


def create_marked_package(package_path, directory, patching_root, release):
    """
    Creates the copy of given package in the given directory and adjusts its
    release number to the given values.

    @param package_path     The path to the marked package.
    @param directory        The destination directory where to save the package
                            copy.
    @param patching_root    The root used for RPM patching.
    @param release          The release number of the corresponding non-marked
                            package.
    """
    if not os.path.isfile(package_path):
        logging.error("File {0} does not exist!".format(package_path))
        sys.exit("Error.")
    shutil.copy(package_path, patching_root)
    package_name = os.path.basename(package_path)

    queue = multiprocessing.Queue()
    child = multiprocessing.Process(target=create_patched_package,
                                    args=(queue, package_name, release,
                                          patching_root,))
    child.start()
    child.join()
    patched_package_name = os.path.basename(queue.get())
    logging.info("The package has been rebuilt to adjust release numbers: "
                 "{0}".format(patched_package_name))
    patched_package_paths = find_files_fast(patching_root,
                                            patched_package_name)
    patched_package_path = None
    if len(patched_package_paths) < 1:
        raise Exception("Failed to find file "
                        "{0}".format(patched_package_name))
    elif len(patched_package_paths) > 1:
        raise Exception("Found multiple files "
                        "{0}".format(patched_package_name))
    else:
        patched_package_path = patched_package_paths[0]
    shutil.copy(patched_package_path, directory)


def construct_combined_repository(graph, marked_graph, marked_packages,
                                  if_mirror, groups, patterns,
                                  patching_root):
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
    @param patching_root    The root used for RPM patching.

    @return             The path to the constructed combined repository.
    """
    repository_path = temporaries.create_temporary_directory("combi-repo")
    packages_not_found = []

    for package in marked_packages:
        marked_package_id = marked_graph.get_name_id(package)
        if marked_package_id is None:
            packages_not_found.append(package)
            continue
        location_from = marked_graph.vs[marked_package_id]["location"]
        version_marked = marked_graph.vs[marked_package_id]["version"]
        release_marked = marked_graph.vs[marked_package_id]["release"]

        package_id = graph.get_name_id(package)
        if package_id is None:
            create_symlink(package, location_from, repository_path)
        else:
            version = graph.vs[package_id]["version"]
            if version != version_marked:
                logging.error("Versions of package {0} differ: {1} and {2}. "
                              "Please go and rebuild the marked "
                              "package!".format(package, version,
                                                version_marked))
                sys.exit("Error.")
            release = graph.vs[package_id]["release"]
            if release != release_marked:
                logging.warning("Release numbers of package {0} differ: "
                                "{1} and {2}, so the marked package will be "
                                "patched so that to match to original release "
                                "number.".format(package, release,
                                                 release_marked))
                create_marked_package(location_from, repository_path,
                                      patching_root, release)
            else:
                create_symlink(package, location_from, repository_path)

    if len(packages_not_found) != 0:
        for package in packages_not_found:
            logging.error("Marked package {0} not found in marked "
                          "repository".format(package))
        if not if_mirror:
            logging.error("The above listed packages were not found in "
                          "marked repository.\n"
                          "HINT: use option -m to use non-marked packages "
                          "instead of them.")
            sys.exit("Error.")

    packages = Set(graph.vs["name"])
    for package in packages:
        if package in marked_packages:
            if package not in packages_not_found:
                continue
        package_id = graph.get_name_id(package)
        location_from = graph.vs[package_id]["location"]
        create_symlink(package, location_from, repository_path)

    if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
        call_hidden_subprocess(["ls", "-l", repository_path])

    construct_repodata(repository_path, groups, patterns)
    return repository_path


def create_image(arch, repository_names, repository_paths, kickstart_file_path,
                 output_directory_path, mic_options, specific_packages,
                 logging_level):
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
        elif line.startswith("%packages"):
            modified_kickstart_file.write(line)
            for package in specific_packages:
                modified_kickstart_file.write("{0}\n".format(package))
        else:
            modified_kickstart_file.write(line)
    kickstart_file.close()
    modified_kickstart_file.close()

    # Now create the image using the "mic" tool:
    mic_command = ["sudo", "mic", "create", "loop",
                   modified_kickstart_file_path, "-A", arch, "-o",
                   output_directory_path, "--tmpfs", "--pkgmgr=zypp"]
    if mic_options is not None:
        mic_command.extend(mic_options)
    logging.info("mic command: {0}".format(" ".join(mic_command)))
    logging_level_initial = logging.getLogger().getEffectiveLevel()
    logging.getLogger().setLevel(logging_level)
    call_hidden_subprocess(mic_command)
    logging.getLogger().setLevel(logging_level_initial)


def find_groups_and_patterns(directory_path):
    """
    Finds the group.xml and patterns.xml in the given directory.

    @param directory_path  The path to the directory.

    @return                 Paths to group.xml and patterns.xml
    """
    all_groups = find_files_fast(directory_path, ".*group\.xml$")
    all_patterns = find_files_fast(directory_path, ".*patterns\.xml$")

    groups = None
    if len(all_groups) > 1:
        logging.warning("Multiple groups XML files found:")
        for file_path in all_groups:
            logging.warning(" * {0}".format(file_path))
        groups = all_groups[0]
        logging.warning("Selecting {0}".format(groups))
    elif len(all_groups) == 1:
        groups = all_groups[0]

    patterns = None
    if len(all_patterns) > 1:
        logging.warning("Multiple patterns XML files found:")
        for file_path in all_patterns:
            logging.warning(" * {0}".format(file_path))
        patterns = all_patterns[0]
    elif len(all_patterns) == 1:
        patterns = all_patterns[0]

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


def process_repository_triplet(triplet, dependency_builder, args,
                               patching_root):
    """
    Processes one repository triplet and constructs combined repository for
    it.

    @param triplet              The repository triplet.
    @param dependency_builder   The dependenct graph builder.
    @param args                 Common parsed command-line arguments.
    @param patching_root        The root used for RPM patching.

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

    strategy = args.preferring_strategy
    graph, back_graph = dependency_builder.build_graph(repository_path,
                                                       args.arch,
                                                       args.preferables,
                                                       strategy)
    # Generally speaking, sets of packages in non-marked and marked
    # repositories can differ. That's why we need to build graphs also for
    # marked repository.
    # Nevertheless we assume that graph of marked repository is isomorphic
    # to some subgraph of the non-marked repository graph.
    # FIXME: If it's not true in some pratical cases, then the special
    # treatment is needed.
    marked_graph, _ = dependency_builder.build_graph(marked_repository_path,
                                                     args.arch,
                                                     args.preferables,
                                                     strategy)
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
                                            args.exclude,
                                            args.specific_packages)
    groups, patterns = find_groups_and_patterns(repository_path)
    combined_repository_path = construct_combined_repository(graph,
                                                             marked_graph,
                                                             marked_packages,
                                                             args.mirror,
                                                             groups,
                                                             patterns,
                                                             patching_root)
    return combined_repository_path, marked_packages


def extract_package_groups_package(repository_path):
    """
    Searches for group.xml and patterns.xml in the package-groups-*.rpm
    package in the given repository (if exists) and returns them.

    @param repository_path  The path to the repository.
    """
    package_groups_package = None

    package_groups_packages = find_files_fast(repository_path,
                                              "^package-groups.*\.rpm$")
    if len(package_groups_packages) > 1:
        logging.warning("Multiple package-groups RPMs found:")
        for package in package_groups_packages:
            logging.warning(" * {0}".format(package))
        package_groups_package = package_groups_packages[0]
        logging.warning("Selecting {0}".format(package_groups_package))
    elif len(package_groups_packages) == 1:
        package_groups_package = package_groups_packages[0]
    if package_groups_package is None:
        return None, None

    package_groups_package = os.path.abspath(package_groups_package)
    directory_unpacking = temporaries.create_temporary_directory("groups")
    initial_directory = os.getcwd()
    os.chdir(directory_unpacking)
    groups = None
    patterns = None
    num_groups_files = 0
    num_patterns_files = 0
    call_hidden_subprocess(["unrpm", package_groups_package])
    groups, patterns = find_groups_and_patterns(directory_unpacking)
    os.chdir(initial_directory)
    return groups, patterns


def regenerate_repodata(repository_path, marked_repository_path):
    """
    Re-generates the repodata for the given repository.

    @param repository_path  The path to the repository.

    Uses group.xml and patterns.xml from any path inside repository, if these
    files don't exist they're unpacked from package-groups.rpm
    """
    groups, patterns = find_groups_and_patterns(repository_path)

    if groups is None or patterns is None:
        groups, patterns = extract_package_groups_package(repository_path)
    else:
        logging.warning("The repository {0} contains files {1} and {2}! They "
                        "will be used as groups and patterns "
                        "files!".format(repository_path, groups, patterns))

    if groups is None or patterns is None:
        logging.warning("There is no group.xml, patterns.xml and valid "
                        "package-groups rpm in the repository! The repository "
                        "will be generated without groups and patterns files!")
    else:
        groups = os.path.abspath(groups)
        patterns = os.path.abspath(patterns)

    construct_repodata(repository_path, groups, patterns)
    construct_repodata(marked_repository_path, groups, patterns)


def check_command_exists(command):
    """
    Checks whether the command exists in the given PATH evironment and exits
    the program in the case of failure.

    @param command  The command.
    @return         True if exists, false if file exists, exits otherwise.
    """
    logging.debug("Checking command \"{0}\"".format(command))
    try:
        DEV_NULL = open(os.devnull, 'w')
        subprocess.call([command], stdout=DEV_NULL, stderr=DEV_NULL)
    except OSError as error:
        if os.path.isfile(command):
            logging.error("File {0} cannot be executed.".format(command))
            return False
        elif error.errno == errno.ENOENT:
            logging.error("\"{0}\" command is not available. Try to "
                          "install it!".format(command))
        else:
            logging.error("Unknown error happened during checking the "
                          "command \"{0}\"!".format(command))
        sys.exit("Error.")
    return True


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


def construct_combined_repositories(args, patching_root):
    """
    Constructs combined repositories based on arguments.

    @param args             The argument of the program.
    @param patching_root    The root used for RPM patching.

    @return         The list of combined repositories' paths.
    """
    dependency_builder = DependencyGraphBuilder()

    combined_repository_paths = []
    marked_packages_total = Set()
    for triplet in args.triplets:
        path, marked_packages = process_repository_triplet(triplet,
                                                           dependency_builder,
                                                           args,
                                                           patching_root)
        marked_packages_total = marked_packages_total | marked_packages
        combined_repository_paths.append(path)

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
    return combined_repository_paths


def find_platform_images(images_directory):
    """
    Finds the platform images in the directory.

    @param images_directory     The directory with built images.
    @return                     The path to the selected images.
    """
    logging.debug("Searching in directory {0}".format(images_directory))
    images = find_files_fast(images_directory, ".*\.img$")

    if len(images) == 0:
        logging.error("No images were found.")
        sys.exit("Error.")
    return images


def produce_architecture_synonyms_list(architecture):
    """
    Produces the list of architecture names that are synonyms or compatible.

    @param architecture The architecture.
    """
    if "arm64" in architecture or "aarch64" in architecture:
        return ["aarch64", "arm64", architecture]
    if "arm" in architecture:
        return ["arm", architecture]
    if "x86_64" in architecture or "86" in architecture:
        return ["x86_64", "x86", architecture]


def unpack_qemu_packages(directory, repositories, architecture, qemu_package):
    """
    Looks for all qemu packages in the given list of repositories and unpacks
    them to the given directory.

    @param directory    The directory where the packages should be unpacked.
    @param repositories The list of repositories.
    @param architecture The architecture of the image.
    @param qemu_package The qemu package specified by user (if any).
    """
    initial_directory = os.getcwd()
    qemu_packages = []

    if qemu_package is None:
        expression = "^qemu.*\.{0}\.rpm$".format(architecture)
        for repository in repositories:
            qemu_packages_portion = find_files_fast(repository, expression)
            qemu_packages.extend(qemu_packages_portion)
        logging.warning("The following qemu packages will be unpacked in "
                        "chroot:")
        for package in qemu_packages:
            logging.warning(" * {0}".format(package))
    else:
        qemu_packages.append(qemu_package)

    os.chdir(directory)
    for package in qemu_packages:
        result = call_hidden_subprocess(["unrpm", package])
        if result != 0:
            logging.error("Failed to unpack package.")
            sys.exit("Error.")
    os.chdir(initial_directory)


def find_qemu_executable(directory, architecture):
    """
    Finds the appropriate qemu executable for the given architecture in the
    given directory.

    @param directory    The buildroot directory.
    @param architecture The architecture of the image.
    """

    # The synonyms for the architecture:
    architectures = produce_architecture_synonyms_list(architecture)
    executables = []
    for arch in architectures:
        qemu_name = "^qemu-{0}$".format(arch)
        qemu_binfmt_name = "^qemu-{0}-binfmt$".format(arch)
        executables_portion = find_files_fast(directory, qemu_binfmt_name)
        executables.extend(executables_portion)
        executables_portion = find_files_fast(directory, qemu_name)
        executables.extend(executables_portion)

    logging.warning("Found several qemu executables:")
    working_executables = []
    for path in executables:
        relative_path = os.path.relpath(path, directory)
        if check_command_exists(path):
            working_executables.append(path)
            summary = "workinig"
        else:
            summary = "not working"
        path = path.replace(directory, "")
        logging.warning(" * /{0} ({1})".format(relative_path, summary))

    if len(working_executables) < 1:
        logging.error("No working qemu executables found!")
        sys.exit("Error.")
    else:
        selected_path = working_executables[0]

    relative_path = os.path.relpath(selected_path, directory)
    logging.warning("The following one was selected: "
                    "{0}".format(relative_path))
    return "/{0}".format(relative_path)


def process_user_qemu_executable(directory, qemu_path):
    """
    Processes the qemu executable specified by user, checks it and in case of
    success copies it to the directory.
    """
    qemu_executable_path = None
    if os.path.isfile(qemu_path):
        # FIXME: Here should be file type checking.
        if not os.path.basename(qemu_path).endswith(".rpm"):
            logging.info("Checking specified qemu executable "
                         "{0}...".format(qemu_path))
            if not check_command_exists(qemu_path):
                logging.error("The specified qemu executable is not working.")
            else:
                install_directory = os.path.join(directory, "usr/local/bin")
                if not os.path.isdir(install_directory):
                    os.makedirs(os.path.join(install_directory))
                install_path = os.path.join(install_directory,
                                            os.path.basename(qemu_path))
                shutil.copy(qemu_path, install_path)
                relative_path = os.path.relpath(install_path, directory)
                qemu_executable_path = "/{0}".format(relative_path)

    else:
        logging.error("Specified file {0} does not exist or is not a "
                      "file!".format(qemu_path))
        sys.exit("Error.")
    return qemu_executable_path


def deploy_qemu_package(directory, repositories, architecture, qemu_path):
    """
    Deploys all qemu packages that can be found in the specified list of
    repositories and that have the specified architecture in the given
    directory.

    @param directory    The direcotory.
    @param repositories The list of repositories' paths.
    @param architecture The architecture of the image.
    @param qemu_path    The qemu package/executable specified by user (if any).
    """
    qemu_executable_path = None
    if qemu_path is not None:
        qemu_executable_path = process_user_qemu_executable(directory,
                                                            qemu_path)

    if qemu_executable_path is None:
        unpack_qemu_packages(directory, repositories, architecture, qemu_path)
        qemu_executable_path = find_qemu_executable(directory, architecture)

    binfmt.disable_all()
    binfmt.register(architecture, qemu_executable_path)


def install_rpmrebuild(queue, chroot_path):
    """
    Chroots to the given path and installs rpmrebuild in it.

    @param chroot_path  The path to the chroot.
    """
    os.chroot(chroot_path)
    os.chdir("/rpmrebuild/src")
    call_hidden_subprocess(["make"])
    call_hidden_subprocess(["make", "install"])
    check_command_exists("rpmrebuild")
    queue.put(True)


def prepare_rpm_patching_root(images_directory, repositories, architecture,
                              qemu_path):
    """
    Prepares the chroot for RPM patching.

    @param images_directory     The directory with built images that will be
                                used as a chroot.
    @param repositories         The list of repositories.
    @param architecture         The architecture of the image.
    @param qemu_path            The qemu package/executable specified by user
                                (if any).

    @return                     The path to the prepared chroot.
    """
    images = find_platform_images(images_directory)

    directory = temporaries.create_temporary_directory("patching_root")

    # For all-in-one images:
    if len(images) == 1:
        temporaries.mount_image(directory, image)
    # For 3-parts images:
    elif len(images) == 3:
        for image in images:
            if os.path.basename(image) == "rootfs.img":
                rootfs_image = image
            elif os.path.basename(image) == "system-data.img":
                system_image = image
            elif os.path.basename(image) == "user.img":
                user_image = image
            else:
                raise Exception("Unknown image name!")

        temporaries.mount_image(directory, rootfs_image)
        system_directory = os.path.join(os.path.join(directory, "opt"))
        if not os.path.isdir(system_directory):
            os.mkdir(system_directory)
        temporaries.mount_image(system_directory, system_image)
        user_directory = os.path.join(system_directory, "usr")
        if not os.path.isdir(user_directory):
            os.mkdir(user_directory)
        temporaries.mount_image(user_directory, user_image)
    else:
        raise Exception("This script is able to handle only all-in-one or "
                        "three-parted images!")

    host_arches = produce_architecture_synonyms_list(platform.machine())
    if architecture not in host_arches:
        deploy_qemu_package(directory, repositories, architecture,
                            qemu_path)

    working_directory = os.path.join(directory, "rpmrebuild")
    combirepo_directory = os.path.dirname(os.path.realpath(__file__))
    rpmrebuild_directory = os.path.join(combirepo_directory, "rpmrebuild")
    if os.path.isdir(working_directory):
        shutil.rmtree(working_directory)
    shutil.copytree(rpmrebuild_directory, working_directory)

    queue = multiprocessing.Queue()
    child = multiprocessing.Process(target=install_rpmrebuild,
                                    args=(queue, directory,))
    child.start()
    child.join()
    if queue.empty():
        logging.error("Failed to install rpmrebuild into chroot.")
        sys.exit("Error.")
    else:
        result = queue.get()
        if result:
            logging.debug("Installation of rpmrebuild successfully "
                          "completed.")
        else:
            raise Exception("Impossible happened.")
    return directory


def prepare_empty_kickstart_file(kickstart_file_path):
    """
    Removes group tags from %packages section so that to provide minimal
    packages set build.

    @param kickstart_file_path  The path to original kickstart file.
    @return                     The path to the patched kickstart file.
    """
    modified_kickstart_file_path = temporaries.create_temporary_file("mod.ks")
    kickstart_file = open(kickstart_file_path, "r")
    modified_kickstart_file = open(modified_kickstart_file_path, "w")

    if_packages_section = False
    for line in kickstart_file:
        if if_packages_section:
            if line.startswith("%end"):
                if_packages_section = False
                modified_kickstart_file.write(line)
            elif line.startswith("@"):
                modified_kickstart_file.write("#{0}".format(line))
            else:
                modified_kickstart_file.write(line)
        elif line.startswith("%packages"):
            if_packages_section = True
            modified_kickstart_file.write(line)
        else:
            modified_kickstart_file.write(line)
    kickstart_file.close()
    modified_kickstart_file.close()
    return modified_kickstart_file_path


if __name__ == '__main__':
    args = parse_args()

    if os.geteuid() != 0:
        print("Changing user to SUDO user...")
        os.execvp("sudo", ["sudo"] + sys.argv)

    # These commands will be called in subprocesses, so we need to be sure
    # that they exist in the current environment:
    for command in ["mic", "createrepo", "modifyrepo", "sudo", "ls", "unrpm"]:
        check_command_exists(command)

    # Check that user has given correct arguments for repository names:
    names = [triplet[0] for triplet in args.triplets]
    check_repository_names(names,
                           args.kickstart_file)

    if args.regenerate_repodata:
        for triplet in args.triplets:
            regenerate_repodata(triplet[1], triplet[2])

    original_repositories = [os.path.abspath(triplet[1]) for triplet
                             in args.triplets]
    original_images_dir = None
    if args.original_image is None:
        if args.outdir_original is None:
            directory = temporaries.create_temporary_directory("orig")
            args.outdir_original = directory
        original_images_dir = args.outdir_original
        kickstart_patched = prepare_empty_kickstart_file(args.kickstart_file)
        create_image(args.arch, names, original_repositories,
                     kickstart_patched, original_images_dir,
                     [],
                     ["shadow-utils", "coreutils",
                      "make", "rpm-build", "sed"],
                     logging.DEBUG)
    else:
        if os.path.isdir(args.original_image):
            original_images_dir = args.original_image
        elif os.path.isfile(args.original_image):
            original_images_dir = os.path.dirname(args.original_image)
        else:
            logging.error("Given {0} is not a file or a "
                          "directory.".format(args.original_image))
            sys.exit("Error.")

    patching_root = prepare_rpm_patching_root(original_images_dir,
                                              original_repositories,
                                              args.arch, args.qemu_path)
    combined_repositories = construct_combined_repositories(args,
                                                            patching_root)
    mic_options = ["--shrink"]
    if args.mic_options is list:
        mic_options.extend(args.mic_options)
    create_image(args.arch, names, combined_repositories,
                 args.kickstart_file, args.outdir, mic_options,
                 args.specific_packages, logging.DEBUG)
