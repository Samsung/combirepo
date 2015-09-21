#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import stat
import shutil
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
import rpm_patcher
from repository import Repository, RepositoryData
from kickstart_parser import KickstartFile
from config_parser import ConfigParser


regenerate_repodata = False


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


def build_package_set(graph, back_graph, package_names):
    """
    Builds the set of marked packages.

    @param graph            The dependency graph of the repository.
    @param back_graph       The backward dependency graph of the repository.
    @param package_names    The package names.

    @return                 The set of marked packages.
    """
    marked = Set()
    for package in package_names["forward"]:
        marked = marked | build_forward_dependencies(graph, package)
    for package in package_names["backward"]:
        marked = marked | build_forward_dependencies(back_graph, package)
    for package in package_names["single"]:
        if not graph.get_name_id(package) is None:
            marked = marked | Set([package])
    for package in package_names["excluded"]:
        if not graph.get_name_id(package) is None:
            marked = marked - Set([package])
    for package in package_names["service"]:
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
    repository_path = temporaries.create_temporary_directory("combirepo")
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
    if repository_names is None or len(repository_names) == 0:
        raise Exception("Repository names are not given! "
                        "{0}".format(repository_names))
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


def process_repository_pair(repository_pair, builder, properties,
                            rpm_patcher):
    """
    Processes one repository triplet and constructs combined repository for
    it.

    @param repository_pair      The repository pair.
    @param builder              The dependency graph builder.
    @param properties           The properties of the repository combiner.
    @param rpm_patcher          The patcher of RPMs.

    @return                     Path to combined repository.
    """
    repository_name = repository_pair.name
    logging.info("Processing repository \"{0}\"".format(repository_name))
    check.directory_exists(repository_pair.url)
    check.directory_exists(repository_pair.url_marked)

    strategy = properties.prefer_strategy
    preferables = properties.package_names["preferable"]
    graph, back_graph = builder.build_graph(repository_pair.url,
                                            properties.architecture,
                                            preferables, strategy)
    # Generally speaking, sets of packages in non-marked and marked
    # repositories can differ. That's why we need to build graphs also for
    # marked repository.
    # Nevertheless we assume that graph of marked repository is isomorphic
    # to some subgraph of the non-marked repository graph.
    # FIXME: If it's not true in some pratical cases, then the special
    # treatment is needed.

    marked_graph, _ = builder.build_graph(repository_pair.url_marked,
                                          properties.architecture,
                                          preferables,
                                          strategy)
    inform_about_unprovided(graph.provided_symbols, graph.unprovided_symbols,
                            marked_graph.provided_symbols,
                            marked_graph.unprovided_symbols)
    if properties.greedy_mode:
        marked_packages = Set(marked_graph.vs["name"])
        for package in marked_packages:
            logging.debug("Package {0} is marked".format(package))
        for package in graph.vs["name"]:
            if package not in marked_packages:
                logging.debug("!!! Package {0} is NOT marked "
                              "!!!".format(package))
    else:
        marked_packages = build_package_set(graph, back_graph,
                                            properties.package_names)
    repository = Repository(repository_pair.url)
    repository.prepare_data()
    repodata = repository.data
    mirror_mode = properties.mirror_mode
    combined_repository_path = construct_combined_repository(graph,
                                                             marked_graph,
                                                             marked_packages,
                                                             mirror_mode,
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


def construct_combined_repositories(properties, rpm_patcher):
    """
    Constructs combined repositories based on arguments.

    @param properties       The properties of the repository combiner.
    @param rpm_patcher      The patcher of RPMs.

    @return         The list of combined repositories' paths.
    """
    dependency_builder = DependencyGraphBuilder()

    combined_repository_paths = []
    marked_packages_total = Set()
    for repository_pair in properties.repository_pairs:
        logging.debug(properties.package_names)
        path, marked_packages = process_repository_pair(repository_pair,
                                                        dependency_builder,
                                                        properties,
                                                        rpm_patcher)
        marked_packages_total = marked_packages_total | marked_packages
        combined_repository_paths.append(path)

    specified_packages = []
    for key in ["forward", "backward", "single", "excluded"]:
        if properties.package_names[key] is not None:
            specified_packages.extend(properties.package_names[key])
    for package in specified_packages:
        if package not in marked_packages_total:
            raise Exception("Failed to find package with name \"{0}\" in any"
                            " of non-marked repositories".format(package))
    return combined_repository_paths


def initialize():
    """
    Initializes the repository combiner.
    """
    if os.geteuid() != 0:
        print("Changing user to SUDO user...")
        os.execvp("sudo", ["sudo"] + sys.argv)

    # These commands will be called in subprocesses, so we need to be sure
    # that they exist in the current environment:
    for command in ["mic", "createrepo", "modifyrepo", "sudo", "ls", "unrpm"]:
        check.command_exists(command)


def combine(properties):
    """
    Combines the repostories based on properties structure.
    """
    if len(properties.repository_pairs) == 0:
        raise Exception("No repository pairs given!")
    initialize()

    # Check that user has given correct arguments for repository names:
    names = [repository_pair.name for repository_pair in
             properties.repository_pairs]
    logging.debug("Repository names: {0}".format(names))
    check_repository_names(names, properties.kickstart_file_path)

    if regenerate_repodata:
        for repository_pair in properties.repository_pairs:
            regenerate_repodata(repository_pair.url,
                                repository_pair.url_marked)

    original_repositories = [repository_pair.url for repository_pair
                             in properties.repository_pairs]
    logging.debug("Original repository URLs: "
                  "{0}".format(original_repositories))
    patcher = rpm_patcher.RpmPatcher(names,
                                     original_repositories,
                                     properties.architecture,
                                     properties.kickstart_file_path)
    patcher.prepare()
    combined_repositories = construct_combined_repositories(properties,
                                                            patcher)
    mic_options = ["--shrink"]
    if properties.mic_options is list:
        mic_options.extend(args.mic_options)
    hidden_subprocess.visible_mode = True
    create_image(properties.architecture, names, combined_repositories,
                 properties.kickstart_file_path,
                 properties.output_directory_path,
                 mic_options,
                 properties.package_names["service"])
    hidden_subprocess.visible_mode = False
