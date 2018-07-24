#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#
# Copyright (C) Samsung Electronics, 2016
#
# 2016         Ilya Palachev                 <i.palachev@samsung.com>

import os
import stat
import shutil
import sys
import logging
import re
from sets import Set
import subprocess
import urlparse
import configparser
import hidden_subprocess
import multiprocessing
import base64
import difflib
from rpmUtils.miscutils import splitFilename
import mic.kickstart
from mic.utils.misc import get_pkglist_in_comps
from dependency_graph_builder import DependencyGraphBuilder
import temporaries
import binfmt
import files
import check
import rpm_patcher
from repository import Repository, RepositoryData
from kickstart_parser import KickstartFile
from config_parser import ConfigParser
from repository_manager import RepositoryManager


repodata_regeneration_enabled = False
target_arhcitecture = None
jobs_number = 1
repository_cache_directory_path = None
mic_config_path = None
libasan_preloading = True


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
        logging.debug("Package {0} is marked".format(package))
    logging.info("Number of marked packages in this repository: "
                 "{0}".format(len(marked)))

    return marked


def check_rpm_versions(graph, marked_graph, packages):
    """
    Checks that versions of packages do not differ, otherwise reports about
    all differencies and aborts the program.

    @param graph            Dependency graph of the non-marked repository
    @param marked_graph     Dependency graph of the marked repository
    @param marked_packages  Set of marked package names
    """
    packages_different = {}
    for package in packages:
        package_id = graph.get_name_id(package)
        if package_id is None:
            continue
        marked_package_id = marked_graph.get_name_id(package)
        if marked_package_id is None:
            continue
        version = graph.vs[package_id]["version"]
        version_marked = marked_graph.vs[marked_package_id]["version"]
        if version != version_marked:
            packages_different[package] = [version, version_marked]

    num_different = len(packages_different.keys())
    if num_different == 0:
        return
    len_package_name_max = max([len(package) for package in
                                packages_different.keys()])
    len_version_max = max([max([len(version) for version in
                                packages_different[package]])
                           for package in packages_different.keys()])
    logging.error("Found {0} packages with different version "
                  "numbers!".format(num_different))
    for package in packages_different.keys():
        [version, version_marked] = packages_different[package]
        logging.error(
            " {package: <{len_package}.{len_package}} "
            "{version: <{len_version}.{len_version}} "
            "{version_marked: <{len_version}.{len_version}}"
            "".format(package=package, len_package=len_package_name_max,
                      version=version, version_marked=version_marked,
                      len_version=len_version_max))
    logging.error("Please go and rebuild them!")
    sys.exit("Error.")


def get_requirements_updates(package_name, requirements_tuples,
                             requirements_marked_tuples):
    """
    Gets the list of requirements that should be updated in the marked RPM
    package.

    @param package_name                 The name of RPM package.
    @param requirements_tuples          The list of requirements of the
                                        original package.
    @param requirements_tuples_marked   The list of requirements of the marked
                                        package.
    @return                             The list of requirements of the
                                        original package that are different
                                        from marked ones.
    """
    logging.debug("Processing requirements of package "
                  "{0}".format(package_name))
    requirements = {}
    for requirement_tuple in requirements_tuples:
        symbol, relation, numbers = requirement_tuple
        epoch, version, release = numbers
        requirements[symbol] = (relation, epoch, version, release)
    requirements_marked = {}
    for requirement_tuple in requirements_marked_tuples:
        symbol, relation, numbers = requirement_tuple
        epoch, version, release = numbers
        requirements_marked[symbol] = (relation, epoch, version, release)

    updates = []
    for symbol in requirements.keys():
        if symbol not in requirements_marked.keys():
            logging.warning("  Marked package \"{0}\" has lost requirement "
                            "\"{1}\"".format(package_name, symbol))
            updates.append(("add", symbol, requirements[symbol]))
            continue
        for i in range(len(requirements[symbol])):
            if requirements[symbol][i] != requirements_marked[symbol][i]:
                logging.debug("  Detected difference in requirement "
                              "{0}:".format(symbol))
                logging.debug("   * {0}".format(requirements[symbol]))
                logging.debug("   * {0}".format(requirements_marked[symbol]))
                updates.append(("change", symbol, requirements[symbol]))
                break
    for symbol in requirements_marked.keys():
        if symbol not in requirements.keys():
            logging.debug("  Marked-specific requirement: "
                          "{0} {1}".format(symbol,
                                           requirements_marked[symbol]))
    if len(updates) > 0:
        logging.debug("  Found {0} updates".format(len(updates)))
    return updates


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

    @return                 The path to the constructed combined repository.
    """
    check_rpm_versions(graph, marked_graph, marked_packages)
    repository_path = temporaries.create_temporary_directory("combirepo")
    packages_not_found = []
    copy_tasks = []

    for package in marked_packages:
        marked_package_id = marked_graph.get_name_id(package)
        if marked_package_id is None:
            packages_not_found.append(package)
            continue
        location_from = marked_graph.vs[marked_package_id]["location"]
        release_marked = marked_graph.vs[marked_package_id]["release"]

        package_id = graph.get_name_id(package)
        if package_id is None:
            copy_tasks.append((package, location_from, repository_path))
        else:
            release = graph.vs[package_id]["release"]
            location_original = graph.vs[package_id]["location"]
            new_name = os.path.basename(location_original)
            location_to = os.path.join(repository_path, new_name)
            if_patching_needed = False
            if release != release_marked:
                logging.debug("Release numbers of package {0} differ: "
                              "{1} and {2}".format(package, release,
                                                   release_marked))
                if_patching_needed = True
            updates = get_requirements_updates(
                package, graph.vs[package_id]["requirements"],
                marked_graph.vs[marked_package_id]["requirements"])
            if len(updates) > 0:
                logging.debug("Requirements updates are necessary.")
                if_patching_needed = True
            if if_patching_needed:
                rpm_patcher.add_task(package, location_from, location_to,
                                     release, updates)
            else:
                copy_tasks.append((package, location_from, repository_path))

    if len(packages_not_found) != 0:
        for package in packages_not_found:
            logging.warning("Marked package {0} not found in marked "
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
        if package in packages_not_found:
            logging.info("Package {0} from original repository will be "
                         "used (mirror mode is on).".format(package))
        package_id = graph.get_name_id(package)
        location_from = graph.vs[package_id]["location"]
        copy_tasks.append((package, location_from, repository_path))

    hidden_subprocess.function_call_list("Copying", shutil.copy, copy_tasks)

    if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
        hidden_subprocess.silent_call(["ls", "-l", repository_path])

    return repository_path


def create_image(arch, repository_names, repository_paths, kickstart_file_path,
                 mic_options, specific_packages):
    """
    Creates an image using MIC tool, from given repository and given kickstart
    file. It creates a copy of kickstart file and replaces "repo" to given
    repository path.

    @param arch                     The architecture of the image
    @param repository_names         The names of repositorues
    @param repository_paths         The repository paths
    @param kickstart_file           The kickstart file to be used
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
    global mic_config_path
    mic_command = ["sudo", "mic", "create", "loop",
                   modified_kickstart_file_path, "-A", arch, "--config",
                   mic_config_path, "--tmpfs"]
    if logging.getLogger().getEffectiveLevel() <= logging.DEBUG:
        mic_options.extend(["--debug", "--verbose"])
    if mic_options is not None:
        mic_command.extend(mic_options)
    hidden_subprocess.call("Building the image", mic_command)


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


def build_graphs(repository_pair, builder, parameters):
    """
    Builds three dependency graphs (forward, backward and marked forward)
    for the given repository pair.

    @param repository_pair      Teh repository pair.
    @param builder              The dependency graph builder.
    @param parameters           The parameters of the repository combiner.
    """
    repository_name = repository_pair.name
    check.directory_exists(repository_pair.url)
    check.directory_exists(repository_pair.url_marked)

    strategy = parameters.preferring_strategy
    preferables = parameters.package_names["preferable"]
    graph, back_graph = builder.build_graph(repository_pair.url,
                                            parameters.architecture,
                                            preferables, strategy)
    # Generally speaking, sets of packages in non-marked and marked
    # repositories can differ. That's why we need to build graphs also for
    # marked repository.
    # Nevertheless we assume that graph of marked repository is isomorphic
    # to some subgraph of the non-marked repository graph.
    # FIXME: If it's not true in some pratical cases, then the special
    # treatment is needed.

    marked_graph, _ = builder.build_graph(repository_pair.url_marked,
                                          parameters.architecture,
                                          preferables,
                                          strategy)
    return graph, back_graph, marked_graph


def process_repository_pair(repository_pair, graphs, parameters,
                            rpm_patcher):
    """
    Processes one repository triplet and constructs combined repository for
    it.

    @param repository_pair      The repository pair.
    @param parameters           The parameters of the repository combiner.
    @param rpm_patcher          The patcher of RPMs.

    @return                     Path to combined repository.
    """
    graph, back_graph, marked_graph = graphs
    inform_about_unprovided(graph.provided_symbols, graph.unprovided_symbols,
                            marked_graph.provided_symbols,
                            marked_graph.unprovided_symbols)
    if parameters.greedy_mode:
        marked_packages = Set(marked_graph.vs["name"])
        for package in marked_packages:
            logging.debug("Package {0} is marked".format(package))
        for package in graph.vs["name"]:
            if package not in marked_packages:
                logging.debug("!!! Package {0} is NOT marked "
                              "!!!".format(package))
    else:
        marked_packages = build_package_set(graph, back_graph,
                                            parameters.package_names)
    mirror_mode = parameters.mirror_mode
    combined_repository_path = construct_combined_repository(graph,
                                                             marked_graph,
                                                             marked_packages,
                                                             mirror_mode,
                                                             rpm_patcher)
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
    if if_error:
        sys.exit("Error.")


def check_package_names(graphs, package_names):
    """
    Checks that given package names really exist in repositories.

    @param graphs           Dependency graphs.
    @param package_names    Package names.
    @return                 The list of specified packages.
    """
    specified_packages = []
    for key in ["forward", "backward", "single", "excluded"]:
        if package_names[key] is not None:
            specified_packages.extend(package_names[key])

    existing_packages = {}
    for key in graphs.keys():
        for graph in graphs[key]:
            for package in graph.id_names.keys():
                if existing_packages.get(package) is None:
                    existing_packages[package] = []
                if key not in existing_packages[package]:
                    existing_packages[package].append(key)

    missing_packages = {}
    for package in specified_packages:
        if package not in existing_packages.keys():
            missing_packages[package] = []
            for candidate in existing_packages.keys():
                ratio = difflib.SequenceMatcher(
                    None, package, candidate).ratio()
                if (ratio > 0.8 or
                        package in candidate or
                        candidate in package):
                    missing_packages[package].append(candidate)

    if len(missing_packages.keys()) > 0:
        for package in missing_packages.keys():
            logging.error("Failed to find package \"{0}\" in any "
                          "repository".format(package))
            for hint in missing_packages[package]:
                logging.warning("   Hint: there is package "
                                "\"{0}\"".format(hint))
                for repository in existing_packages[hint]:
                    logging.warning("                          in repository "
                                    "\"{0}\"".format(repository))
            if len(missing_packages[package]) > 0:
                logging.warning("         Maybe you made a typo?")
        sys.exit("Error.")
    return specified_packages


def construct_combined_repositories(parameters, packages):
    """
    Constructs combined repositories based on arguments.

    @param parameters       The parameters of the repository combiner.
    @param packages         The list of package names that should be installed
                            to the image with all their dependencies.

    @return                 The list of combined repositories' paths.
    """
    dependency_builder = DependencyGraphBuilder(check_rpm_name, packages)

    graphs = {}
    for repository_pair in parameters.repository_pairs:
        graphs[repository_pair.name] = build_graphs(
            repository_pair, dependency_builder, parameters)
    specified_packages = check_package_names(graphs, parameters.package_names)

    # Prepare RPM patching root based on original dependency graphs:
    original_repositories = [repository_pair.url for repository_pair
                             in parameters.repository_pairs]
    names = [repository_pair.name for repository_pair
             in parameters.repository_pairs]
    patcher = rpm_patcher.RpmPatcher(
        names, original_repositories, parameters.architecture,
        parameters.kickstart_file_path,
        [graphs[key][0] for key in graphs.keys()])

    combined_repository_paths = {}
    marked_packages_total = Set()
    for repository_pair in parameters.repository_pairs:
        logging.debug(parameters.package_names)
        path, marked_packages = process_repository_pair(
            repository_pair, graphs[repository_pair.name], parameters,
            patcher)
        marked_packages_total = marked_packages_total | marked_packages
        combined_repository_paths[repository_pair.name] = path

    excluded_packages = parameters.package_names.get("excluded")
    if excluded_packages is None:
        excluded_packages = []
    for package in specified_packages:
        if (package not in marked_packages_total and
                package not in excluded_packages):
            raise Exception("Failed to find package with name \"{0}\" in any"
                            " of non-marked repositories".format(package))
    patcher.do_tasks()
    for repository_pair in parameters.repository_pairs:
        repository = Repository(repository_pair.url)
        repository.prepare_data()
        repodata = repository.data
        combined_repository = Repository(
            combined_repository_paths[repository_pair.name])
        combined_repository.set_data(repodata)
        combined_repository.generate_derived_data()
    return [combined_repository_paths[key] for key in
            combined_repository_paths.keys()]


def initialize():
    """
    Initializes the repository combiner.
    """
    if os.geteuid() != 0:
        print("Changing user to SUDO user...")
        os.execvp("sudo", ["sudo"] + sys.argv)

    # These commands will be called in subprocesses, so we need to be sure
    # that they exist in the current environment:
    for command in ["mic", "createrepo", "modifyrepo", "sudo", "ls",
                    "rpm2cpio", "cpio"]:
        if not check.command_exists(command):
            sys.exit("Error.")


def check_rpm_name(rpm_name):
    """
    Checks whether the RPM with the given name has to be dowloaded and
    processed.

    @param rpm_name     The name of RPM package
    """
    file_name = None
    # If the given name is remote location, then we analyze whether we should
    # download it:
    url_parsed = urlparse.urlparse(rpm_name)
    if url_parsed.netloc is not None and len(url_parsed.netloc) > 0:
        logging.debug("Name {0} is detected as a URL "
                      "location {1}.".format(rpm_name, url_parsed))
        # All non-RPM files should be downloaded:
        if not rpm_name.endswith(".rpm"):
            return True
        # Not all RPMs should be downloaded:
        else:
            file_name = rpm_name.split('/')[-1].split('#')[0].split('?')[0]
    # The only other case when we process the file is the existing file in the
    # filesystem:
    elif os.path.isfile(rpm_name):
        file_name = os.path.basename(rpm_name)
    # In case if we are given RPM name from yum, we should make full name from
    # it before parsing:
    else:
        if not rpm_name.endswith(".rpm"):
            file_name = rpm_name + ".rpm"
        if os.path.basename(file_name) != file_name:
            file_name = os.path.basename(file_name)

    logging.debug("Processing argument {0} with RPM name "
                  "{1} ...".format(rpm_name, file_name))

    components = splitFilename(file_name)
    for component in components:
        if component is None:
            logging.error("Failed to parse argument {0} with RPM name "
                          "{1}, result is {2}!".format(rpm_name, file_name,
                                                       components))
            return False

    (name, version, release, epoch, architecture) = components
    if architecture not in [target_arhcitecture, "noarch"]:
        logging.debug("Target architecture is {0}".format(target_arhcitecture))
        logging.debug("It is indended for another architecture, skipping...")
        return False
    elif "debuginfo" in name or "debugsource" in name:
        logging.debug("It is debug package, skipping...")
        return False
    else:
        logging.debug("Passed...")
        return True


def get_kickstart_from_repos(repository_pairs, kickstart_substring):
    """
    Gets kickstart files from repositories that are used during the build.

    @param repository_pairs     The repository pairs used during the image
                                building.
    @param kickstart_substring  The substring that specifies the substring of
                                kickstart file name to be used.
    """
    if kickstart_substring is None:
        kickstart_substring = ""
    image_configurations_rpms = {}
    for repository_pair in repository_pairs:
        path = repository_pair.url
        rpms = files.find_fast(path, "image-configurations-.*\.rpm")
        image_configurations_rpms[repository_pair.name] = rpms
    logging.debug("Found following image-configurations RPMs: "
                  "{0}".format(image_configurations_rpms))

    kickstart_file_paths = {}
    for key in image_configurations_rpms.keys():
        for rpm in image_configurations_rpms[key]:
            directory_path = temporaries.create_temporary_directory("unpack")
            files.unrpm(rpm, directory_path)
            kickstart_file_paths[key] = files.find_fast(directory_path,
                                                        ".*.ks")
    logging.info("Found following kickstart files:")
    all_kickstart_file_paths = []
    for key in kickstart_file_paths.keys():
        logging.info(" * in repository {0}:".format(key))
        for kickstart_file_path in kickstart_file_paths[key]:
            basename = os.path.basename(kickstart_file_path)
            all_kickstart_file_paths.append(kickstart_file_path)
            logging.info("    * {0}".format(basename))
        if len(kickstart_file_paths[key]) == 0:
            logging.info("    <no kickstart files in this repository>")
    logging.debug("Found files: {0}".format(all_kickstart_file_paths))
    helper_string = "use option -k for that or \"kickstart = ...\" in config"
    kickstart_file_path_resulting = None
    if len(all_kickstart_file_paths) > 1:
        matching_kickstart_file_paths = []
        for kickstart_file_path in all_kickstart_file_paths:
            basename = os.path.basename(kickstart_file_path)
            if kickstart_substring in basename:
                matching_kickstart_file_paths.append(kickstart_file_path)
        if len(matching_kickstart_file_paths) > 1:
            logging.error("More than one kickstart files satisfy the "
                          "substring, or no substring was specified!")
            for kickstart_file_path in matching_kickstart_file_paths:
                basename = os.path.basename(kickstart_file_path)
                logging.error(" * {0}".format(basename))
            logging.error("Please, specified the unique name of kickstart "
                          "file or the unique substring! "
                          "({0}).".format(helper_string))
            sys.exit("Error.")
        elif len(matching_kickstart_file_paths) == 1:
            kickstart_file_path_resulting = matching_kickstart_file_paths[0]
        else:
            logging.error("No matching kickstart files found in repositories, "
                          "please specify another path to the kickstart file! "
                          "({0}).".format(helper_string))
            sys.exit("Error.")
    elif len(all_kickstart_file_paths) == 1:
        kickstart_file_path_resulting = all_kickstart_file_paths[0]
    else:
        logging.error("No kickstart files found in repositories, please "
                      "specify the path to kickstart file manually! "
                      "({0}).".format(helper_string))
        sys.exit("Error.")
    return kickstart_file_path_resulting


def prepare_repositories(parameters):
    """
    Prepares repository pairs for use.

    @param parameters           The combirepo run-time parameters (for
                                explanation, see combirepo/parameters.py).
    @return                     The path to the used kickstart file.
    """
    repository_pairs = parameters.repository_pairs
    kickstart_file_path = parameters.kickstart_file_path
    if len(repository_pairs) == 0:
        raise Exception("No repository pairs given!")
    # Check that user has given correct arguments for repository names:
    names = [repository_pair.name for repository_pair in repository_pairs]
    logging.debug("Repository names: {0}".format(names))
    if kickstart_file_path is not None and os.path.isfile(kickstart_file_path):
        logging.info("Kickstart file {0} specified by user will be "
                     "used".format(kickstart_file_path))
        check_repository_names(names, kickstart_file_path)
    global repository_cache_directory_path
    repository_manager = RepositoryManager(repository_cache_directory_path,
                                           check_rpm_name)
    authenticator = base64.encodestring("{0}:{1}".format(parameters.user,
                                                         parameters.password))
    authenticator = authenticator.replace('\n', '')
    path = repository_manager.prepare(parameters.sup_repo_url, authenticator)
    parameters.sup_repo_url = path
    for repository_pair in repository_pairs:
        path = repository_manager.prepare(repository_pair.url, authenticator)
        repository_pair.url = path
        path_marked = repository_manager.prepare(repository_pair.url_marked,
                                                 authenticator)
        repository_pair.url_marked = path_marked

    if repodata_regeneration_enabled:
        for repository_pair in parameters.repository_pairs:
            regenerate_repodata(repository_pair.url,
                                repository_pair.url_marked)
    if kickstart_file_path is None or not os.path.isfile(kickstart_file_path):
        kickstart_file_path = get_kickstart_from_repos(repository_pairs,
                                                       kickstart_file_path)
        check.file_exists(kickstart_file_path)
        check_repository_names(names, kickstart_file_path)
    logging.info("The following kickstart file will be used: "
                 "{0}".format(kickstart_file_path))
    return kickstart_file_path


def resolve_groups(repositories, kickstart_file_path):
    """
    Resolves packages groups from kickstart file.

    @param repositories         The list of original repository URLs.
    @param kickstart_file_path  The path to the kickstart file.
    @return                     The list of package names.
    """
    groups_paths = []
    for url in repositories:
        repository = Repository(url)
        repository.prepare_data()
        groups_data = repository.data.groups_data
        if groups_data is not None and len(groups_data) > 0:
            groups_path = temporaries.create_temporary_file("group.xml")
            with open(groups_path, "w") as groups_file:
                groups_file.writelines(groups_data)
            groups_paths.append(groups_path)
    logging.debug("Following groups files prepared:")
    for groups_path in groups_paths:
        logging.debug(" * {0}".format(groups_path))
    try:
        parser = mic.kickstart.read_kickstart(kickstart_file_path)
        groups = mic.kickstart.get_groups(parser)
        packages = set(mic.kickstart.get_packages(parser))
    except mic.utils.errors.KsError as err:
        logging.error("Failed to read kickstart file:")
        logging.error(str(err))
        sys.exit("Error.")

    for group in groups:
        group_pkgs = [
            pkg
            for path in groups_paths
            for pkg in get_pkglist_in_comps(group.name, path)
        ]
        logging.debug("Group {0} contains {1} packages.".format(group.name, len(group_pkgs)))
        packages.update(group_pkgs)

    return list(packages)


def generate_mic_config(output_directory_path, temporary_directory_path):
    """
    Generates mic config with changed locations of cachedir, tmpdir, rootdir.

    @param output_directory_path    The path to the mic output directory.
    @param temporary_directory_path The path to cache directory root.
    """
    mic_directory_path = os.path.join(temporary_directory_path, "mic")
    mic_cache_directory_path = os.path.join(mic_directory_path, "cache")
    mic_bootstrap_directory_path = os.path.join(mic_directory_path,
                                                "bootstrap")
    if not os.path.isdir(mic_directory_path):
        os.makedirs(mic_directory_path)
        logging.debug("Created directory for mic's cache "
                      "{0}".format(mic_directory_path))
    parser = configparser.SafeConfigParser()
    mic_config_path = temporaries.create_temporary_file(".mic.conf")
    mic_config_path_default = "/etc/mic/mic.conf"
    # FIXME: Maybe it will be better to always generate config from scratch?
    if not os.path.isfile(mic_config_path_default):
        logging.warning("Cannot find {0}".format(mic_config_path_default))
        parser.add_section("common")
        parser.set("common", "distro_name", "Tizen")
        # FIXME: Is it corect to hardcode paths in a such way?
        parser.set("common", "plugin_dir", "/usr/lib/mic/plugins")
        parser.add_section("create")
        parser.set("create", "runtime", "bootstrap")
        # FIXME: Do we need some abstraction here?
        parser.set("bootstrap", "packages", "mic-bootstrap-x86-arm")
    else:
        shutil.copy(mic_config_path_default, mic_config_path)
        parser.read(mic_config_path)
        for section in ["create", "bootstrap"]:
            if not parser.has_section(section):
                logging.warning("Config {0} does not has section "
                                "\"{1}\"!".format(mic_config_path_default,
                                                  section))
                parser.add_section(section)
    parser.set("create", "tmpdir", mic_directory_path)
    parser.set("create", "cachedir", mic_cache_directory_path)
    parser.set("create", "outdir", output_directory_path)
    package_manager = None
    if rpm_patcher.developer_disable_patching:
        package_manager = "yum"
    else:
        package_manager = "zypp"
    parser.set("create", "pkgmgr", package_manager)
    parser.set("bootstrap", "rootdir", mic_bootstrap_directory_path)

    with open(mic_config_path, "wb") as mic_config:
        parser.write(mic_config)
    with open(mic_config_path, "r") as mic_config:
        logging.debug("Using following mic config file:")
        for line in mic_config:
            logging.debug(line)
    return mic_config_path


def initialize_cache_directories(output_directory_path,
                                 temporary_directory_path):
    """
    Initializes cache directories specified by user or set by default.

    @param output_directory_path    The path to the mic output directory.
    @param temporary_directory_path The path to cache directory root.
    """
    if temporary_directory_path is None:
        temporary_directory_path = "/var/tmp/combirepo"
        logging.debug("Using default cache directory "
                      "{0}".format(temporary_directory_path))
    else:
        temporary_directory_path = os.path.realpath(temporary_directory_path)
        logging.debug("Using custom cache directory "
                      "{0}".format(temporary_directory_path))
    if not os.path.isdir(temporary_directory_path):
        os.makedirs(temporary_directory_path)
        logging.debug("Created cache directory "
                      "{0}".format(temporary_directory_path))
    temporaries.default_directory = os.path.join(temporary_directory_path,
                                                 "temporaries")
    if not os.path.isdir(temporaries.default_directory):
        os.makedirs(temporaries.default_directory)
        logging.debug("Created directory for temporary files "
                      "{0}".format(temporaries.default_directory))
    global repository_cache_directory_path
    repository_cache_directory_path = os.path.join(temporary_directory_path,
                                                   "repositories")
    if not os.path.isdir(repository_cache_directory_path):
        os.makedirs(repository_cache_directory_path)
        logging.debug("Created directory for repositories "
                      "{0}".format(repository_cache_directory_path))
    global mic_config_path
    mic_config_path = generate_mic_config(output_directory_path,
                                          temporary_directory_path)
    patching_cache_path = os.path.join(temporary_directory_path,
                                       "patching_cache")
    if not os.path.isdir(patching_cache_path):
        os.makedirs(patching_cache_path)
        logging.debug("Created directory for patching cache "
                      "{0}".format(patching_cache_path))
    rpm_patcher.patching_cache_path = patching_cache_path


def prepend_preload_library(library_name, output_directory_path):
    """
    Prepends library
    """
    library_paths = files.find_fast(output_directory_path,
                                    "{0}.so.*".format(library_name))
    library_paths_real = []
    library_path_real = None
    for library_path in library_paths:
        if not os.path.islink(library_path):
            library_paths_real.append(library_path)
    if len(library_paths_real) > 1:
        logging.warning("Found several libraries {0}".format(library_name))
        for library_path in library_paths_real:
            logging.warning(" * {0}".format(library_path))
    elif len(library_paths_real) < 1:
        logging.error("Found no libraries {0}".format(library_name))
        sys.exit("Error.")
    library_path_real = library_paths_real[0]
    library_basename = os.path.basename(library_path_real)

    root = temporaries.mount_firmware(output_directory_path)
    ld_preload_path = os.path.join(root, "etc/ld.so.preload")
    lines = ["{0}\n".format(library_basename)]
    if os.path.isfile(ld_preload_path):
        with open(ld_preload_path, "r") as ld_preload:
            for line in ld_preload:
                if not line.startswith(library_name):
                    lines.append(line)
    with open(ld_preload_path, "w") as ld_preload:
        for line in lines:
            ld_preload.write(line)


def combine(parameters):
    """
    Combines the repostories based on parameters structure.

    @param parameters   The parameters of combirepo run.
    """
    initialize_cache_directories(parameters.output_directory_path,
                                 parameters.temporary_directory_path)

    global target_arhcitecture
    target_arhcitecture = parameters.architecture
    parameters.kickstart_file_path = prepare_repositories(parameters)

    original_repositories = [repository_pair.url for repository_pair
                             in parameters.repository_pairs]
    logging.debug("Original repository URLs: "
                  "{0}".format(original_repositories))
    packages = resolve_groups(original_repositories,
                              parameters.kickstart_file_path)
    logging.debug("Packages:")
    for package in packages:
        logging.debug(" * {0}".format(package))
    names = [repository_pair.name for repository_pair
             in parameters.repository_pairs]
    initialize()
    combined_repositories = construct_combined_repositories(parameters,
                                                            packages)
    mic_options = ["--shrink"]
    if parameters.mic_options is list:
        mic_options.extend(parameters.mic_options)
    hidden_subprocess.visible_mode = True

    ks_modified_path = temporaries.create_temporary_file("mod.ks")
    shutil.copy(parameters.kickstart_file_path, ks_modified_path)
    kickstart_file = KickstartFile(ks_modified_path)
    if parameters.sup_repo_url is not None:
        kickstart_file.prepend_repository_path("supplementary",
                                               parameters.sup_repo_url)
    parameters.kickstart_file_path = ks_modified_path
    create_image(parameters.architecture, names, combined_repositories,
                 parameters.kickstart_file_path,
                 mic_options,
                 parameters.package_names["service"])
    hidden_subprocess.visible_mode = False

    if "libasan" in parameters.package_names["service"] and libasan_preloading:
        images_dict = kickstart_file.get_images_mount_points()
        prepend_preload_library("libasan", parameters.output_directory_path, images_dict)
