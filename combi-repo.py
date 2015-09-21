#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import stat
import shutil
import argparse
import sys
import logging
import re
from sets import Set
import subprocess
import hidden_subprocess
import multiprocessing
from dependency_graph_builder import DependencyGraphBuilder
import temporaries
import binfmt
import files
import check
from rpm_patcher import RpmPatcher
from repository import Repository, RepositoryData
from kickstart_parser import KickstartFile
from strings import split_names_list


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
        hidden_subprocess.visible_mode = True
    if args.verbose:
        logging_level = logging.DEBUG
        hidden_subprocess.visible_mode = True
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


def construct_combined_repository(graph, marked_graph, marked_packages,
                                  if_mirror, rpm_patcher):
    """
    Constructs the temporary repository that consists of symbolic links to
    packages from non-marked and marked repositories.

    @param graph            Dependency graph of the non-marked repository
    @param marked_graph     Dependency graph of the marked repository
    @param marked_packages  Set of marked package names
    @param if_mirror        Whether to mirror not found marked packages from
                            non-marked repository
    @param rpm_patcher      The patcher of RPMs.

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
            files.create_symlink(package, location_from, repository_path)
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
                rpm_patcher.patch(location_from, repository_path, release)
            else:
                files.create_symlink(package, location_from, repository_path)

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
        files.create_symlink(package, location_from, repository_path)

    if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
        hidden_subprocess.call(["ls", "-l", repository_path])

    return repository_path


def create_image(arch, repository_names, repository_paths, kickstart_file_path,
                 output_directory_path, mic_options, specific_packages):
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
    @param specific_packages        Packages that must be additionally
                                    installed.
    """
    modified_kickstart_file_path = temporaries.create_temporary_file("mod.ks")
    shutil.copy(kickstart_file_path, modified_kickstart_file_path)
    kickstart_file = KickstartFile(modified_kickstart_file_path)
    kickstart_file.replace_repository_paths(repository_names,
                                            repository_paths)
    kickstart_file.add_packages(specific_packages)

    # Now create the image using the "mic" tool:
    mic_command = ["sudo", "mic", "create", "loop",
                   modified_kickstart_file_path, "-A", arch, "-o",
                   output_directory_path, "--tmpfs", "--pkgmgr=zypp"]
    if mic_options is not None:
        mic_command.extend(mic_options)
    logging.info("mic command: {0}".format(" ".join(mic_command)))
    hidden_subprocess.call(mic_command)


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
                               rpm_patcher):
    """
    Processes one repository triplet and constructs combined repository for
    it.

    @param triplet              The repository triplet.
    @param dependency_builder   The dependenct graph builder.
    @param args                 Common parsed command-line arguments.
    @param rpm_patcher      The patcher of RPMs.

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
    repository = Repository(repository_path)
    repository.prepare_data()
    repodata = repository.data
    combined_repository_path = construct_combined_repository(graph,
                                                             marked_graph,
                                                             marked_packages,
                                                             args.mirror,
                                                             rpm_patcher)
    combined_repository = Repository(combined_repository_path)
    combined_repository.set_data(repodata)
    combined_repository.generate_derived_data()
    return combined_repository_path, marked_packages


def regenerate_repodata(repository_path, marked_repository_path):
    """
    Re-generates the repodata for the given repository.

    @param repository_path  The path to the repository.

    Uses group.xml and patterns.xml from any path inside repository, if these
    files don't exist they're unpacked from package-groups.rpm
    """
    repository = Repository(repository_path)
    repodata = repository.get_data()
    if repodata.groups_data is None:
        logging.warning("There is no groups data in "
                        "{0}".format(repository_path))
    if repodata.patterns_data is None:
        logging.warning("There is no patterns data in "
                        "{0}".format(repository_path))
    repository.generate_derived_data()

    marked_repository = Repository(marked_repository_path)
    marked_repository.set_data(repodata)
    marked_repository.generate_derived_data()


def check_repository_names(names, kickstart_file_path):
    """
    Checks whether all names specified by user exist in the given kickstart
    file.

    @param names                The list of names specified by user.
    @param kickstart_file_path  The kickstart file.
    """
    kickstart_file = KickstartFile(kickstart_file_path)
    possible_names = kickstart_file.get_repository_names()
    if_error = False
    for name in names:
        if name not in possible_names:
            logging.error("Failed to find repository name "
                          "{0} in kickstart "
                          "file {1} specified "
                          "by user.".format(name, kickstart_file_path))
            logging.error("Possible names are: {0}".format(possible_names))
            if_error = True


def construct_combined_repositories(args, rpm_patcher):
    """
    Constructs combined repositories based on arguments.

    @param args             The argument of the program.
    @param rpm_patcher      The patcher of RPMs.

    @return         The list of combined repositories' paths.
    """
    dependency_builder = DependencyGraphBuilder()

    combined_repository_paths = []
    marked_packages_total = Set()
    for triplet in args.triplets:
        path, marked_packages = process_repository_triplet(triplet,
                                                           dependency_builder,
                                                           args,
                                                           rpm_patcher)
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


def prepare_empty_kickstart_file(kickstart_file_path):
    """
    Removes group tags from %packages section so that to provide minimal
    packages set build.

    @param kickstart_file_path  The path to original kickstart file.
    @return                     The path to the patched kickstart file.
    """
    modified_kickstart_file_path = temporaries.create_temporary_file("mod.ks")
    shutil.copy(kickstart_file_path, modified_kickstart_file_path)
    kickstart_file = KickstartFile(modified_kickstart_file_path)
    kickstart_file.comment_all_groups()
    return modified_kickstart_file_path


if __name__ == '__main__':
    args = parse_args()

    if os.geteuid() != 0:
        print("Changing user to SUDO user...")
        os.execvp("sudo", ["sudo"] + sys.argv)

    # These commands will be called in subprocesses, so we need to be sure
    # that they exist in the current environment:
    for command in ["mic", "createrepo", "modifyrepo", "sudo", "ls", "unrpm"]:
        check.command_exists(command)

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
                      "make", "rpm-build", "sed"])
    else:
        if os.path.isdir(args.original_image):
            original_images_dir = args.original_image
        elif os.path.isfile(args.original_image):
            original_images_dir = os.path.dirname(args.original_image)
        else:
            logging.error("Given {0} is not a file or a "
                          "directory.".format(args.original_image))
            sys.exit("Error.")

    rpm_patcher = RpmPatcher(original_images_dir, original_repositories,
                             args.arch, args.qemu_path)
    rpm_patcher.prepare()
    combined_repositories = construct_combined_repositories(args, rpm_patcher)
    mic_options = ["--shrink"]
    if args.mic_options is list:
        mic_options.extend(args.mic_options)
    hidden_subprocess.visible_mode = True
    create_image(args.arch, names, combined_repositories,
                 args.kickstart_file, args.outdir, mic_options,
                 args.specific_packages)
    hidden_subprocess.visible_mode = False
