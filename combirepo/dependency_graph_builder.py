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

import logging
import os
import sys
import re
from iniparse import ConfigParser
import yum
import cStringIO
from sets import Set
import igraph
import temporaries
import check
import hidden_subprocess


class DependencyGraph(igraph.Graph):
    """
    Wrapper of igraph.Graph used for fast search of vertices by their names.
    """
    def __init__(self):
        """
        Initializes the dependency graph.

        @return Empty dependency graph.
        """
        super(DependencyGraph, self).__init__(directed=True)
        self.id_names = {}
        self.provided_symbols = Set()
        self.unprovided_symbols = Set()
        self.symbol_providers = {}

    def set_name_id(self, name, id_):
        """
        Sets the ID of the given name to the given value.

        @param name     The name of package.
        @param id_      Its ID in the vertex list.
        """
        self.id_names[name] = id_

    def get_name_id(self, name):
        """
        Gets the ID of the given name.

        @param name     The name of package.

        @return         The ID of package in the vertex list.
        """
        if name in self.id_names.keys():
            return self.id_names[name]
        else:
            return None

    def get_provider_names(self, symbol):
        """
        Gets names of RPM package that provide the given symbol.

        @param symbol   The symbol.
        @return         Package names.
        """
        logging.debug("Getting provider for symbol {0}".format(symbol))
        logging.debug("Total number of symbols: "
                      "{0}".format(len(self.symbol_providers)))
        names = []
        name = self.symbol_providers.get(symbol)

        if name is None:
            for key in self.symbol_providers.keys():
                key_basename = os.path.basename(key)
                symbol_basename = os.path.basename(symbol)
                if (key_basename == symbol_basename or
                        (key_basename.startswith(symbol_basename) and
                            key_basename[len(symbol_basename)] == '(')):
                    names.append(self.symbol_providers[key])
        else:
            names = [name]
        return names


def _get_full_package_name(package):
    """
    Gets full package name from the package, e. g.:

    name-1.1.1-1.1.armv7l

    @param package  YUM package object from YUM package sack.

    @return         Full package name.
    """
    file_name = "{0}-{1}-{2}.{3}".format(package.name, package.version,
                                         package.release, package.arch)
    return file_name


def _get_package_version_release(package):
    """
    Gets the quadruple of version + release of package.

    @param package  The package.
    """
    result = []
    version = package.version.split(".")
    logging.debug("  version: {0}".format(version))
    result.extend(version)
    release = package.release.split(".")
    logging.debug("  release: {0}".format(release))
    result.extend(release)
    return result


def _check_names_are_equal(packages):
    """
    Checks whether the names of packages are equal, otherwise aborts the
    program.

    @param packages The list of packages.
    """
    short_names = Set()
    for package in packages:
        short_names = short_names | Set([package.name])

    if len(short_names) > 1:
        logging.error("Cannot select extreme package, because there are "
                      "several different with different names:")
        for package in packages:
            full_name = _get_full_package_name(package)
            logging.error(" * {0}".format(full_name))
        logging.error("Please, specify only one of them using option \"-p\"")
        sys.exit("Error.")


def _get_extreme_package(packages, strategy):
    """
    Gets the extreme package (with given strategy).

    @param package  The package.
    @param strategy The strategy.
    """
    _check_names_are_equal(packages)
    small = None
    small_numbers = _get_package_version_release(packages[0])
    big = None
    big_numbers = _get_package_version_release(packages[0])
    default_length = len(small_numbers)

    for package in packages:
        numbers = _get_package_version_release(package)
        if (len(numbers) != default_length):
            logging.error("Package versions are incomparable.")
            logging.error("Please, specify only one of them using "
                          "option \"-p\"")
            sys.exit("Error.")
        if_smaller = True
        for i in range(len(numbers)):
            if numbers[i] < small_numbers[i]:
                if_smaller = True
                break
            if numbers[i] > small_numbers[i]:
                if_smaller = False
                break
        if if_smaller:
            small = package
            small_numbers = numbers

        if_bigger = True
        for i in range(len(numbers)):
            if numbers[i] < big_numbers[i]:
                if_bigger = False
                break
            if numbers[i] > big_numbers[i]:
                if_bigger = True
                break
        if if_bigger:
            big = package
            big_numbers = numbers

    provider = None
    if strategy == "small":
        provider = small
        logging.warning("Package {0} was preferred, because its numbers are "
                        "the smallest".format(provider))
    elif strategy == "big":
        provider = big
        logging.warning("Package {0} was preferred, because its numbers are "
                        "the biggest".format(provider))
    else:
        logging.error("Unknown strategy: {0}".format(strategy))
        sys.exit("Error.")
    return provider


def _handle_have_choice_problem(requirement, providers, preferables, strategy):
    """
    Processes the provider in case of "have choice" problem.

    @param requirement  The name of required symbol.
    @param providers    The list of providers.
    @param preferables  The list of prefered package names.
    @param strategy     The strategy for the case of equal names.

    @return             The name of package to be used.
    """
    provider = None
    logging.warning("Have choice for symbol {0}:".
                    format(requirement))
    preferred_alternatives = []
    preferred_alternatives_exact = []
    names = Set()
    full_names = Set()
    for alternative in providers:
        full_name = _get_full_package_name(alternative)
        logging.warning(" * {0}, version {1}, "
                        "release {2}".format(full_name, alternative.version,
                                             alternative.release))
        if alternative.name in preferables:
            preferred_alternatives.append(alternative)
        if full_name in preferables:
            preferred_alternatives_exact.append(alternative)
        names = names | Set([alternative.name])
        full_names = full_names | Set([full_name])

    if len(preferred_alternatives_exact) == 1:
        provider = preferred_alternatives_exact[0].name
        full_name = _get_full_package_name(provider)
        logging.warning("Package full name {0} is specified as preferable "
                        "and will be used to resolve this "
                        "choice.".format(full_name))
    elif len(preferred_alternatives) == 1:
        provider = preferred_alternatives[0].name
        logging.warning("Package name {0} is specified as preferable "
                        "and will be used to resolve this "
                        "choice.".format(provider))
    else:
        if len(preferred_alternatives_exact) > 1:
            logging.warning("All of the following packages are "
                            "specified as preferable:")
            for alternative in preferred_alternatives:
                full_name = _get_full_package_name(alternative)
                logging.warning(" * {0}".format(full_name))
            providers = preferred_alternatives_exact
        elif len(preferred_alternatives) > 1:
            logging.warning("All of the following packages are "
                            "specified as preferable:")
            for alternative in preferred_alternatives:
                logging.warning(" * {0}".format(alternative.name))
            logging.warning("Please specify only one of them.")
            providers = preferred_alternatives
        if strategy is not None:
            provider = _get_extreme_package(providers, strategy).name
            return provider

        logging.error("Please specify one and only one package "
                      "from above listed alternatives that should be used. "
                      "Use option \"-p\" for that.")
        if len(names) != len(full_names):
            logging.error("You should specify one and only one FULL name "
                          "as argument.")
        else:
            logging.error("You should specify one and only one SHORT name "
                          "as argument.")
        logging.debug("Preferables: {0}".format(preferables))
        sys.exit("\"Have choice\" error!")
    return provider


def _search_dependencies(yum_sack, package, providers, preferables, strategy):
    """
    Searches the dependencies of the given package in the repository

    @param yum_sack     The YUM sack used to search packages.
    @param package      The package which dependencies are searched.
    @param providers    Cached RPM symbols providers.
    @param strategy     Have choice resolving strategy.

    @return             List of package names on which the given package
                        depends on
    """
    logging.debug("Processing package: {0}".format(package))
    # Hash of already built dependencies.
    # FIXME: This hash is used just as a set, not as a hash.
    dependencies = {}
    provided_symbols = Set()
    unprovided_symbols = Set()

    for requirement in package.returnPrco('requires'):
        logging.debug("   requirement: {0}".format(requirement))
        requirement_name = requirement[0]

        if requirement_name.startswith("rpmlib"):
            continue

        # Search the provider.
        # If the provider is already cached, use it to speed up the
        # search
        if requirement_name in providers:
            provider = providers[requirement_name]
        else:
            provider = yum_sack.searchProvides(requirement_name)

            if not provider:
                element = Set([requirement_name])
                unprovided_symbols = unprovided_symbols | element
                continue
            else:
                element = Set([requirement_name])
                provided_symbols = provided_symbols | element
                if len(provider) != 1:
                    provider = _handle_have_choice_problem(requirement_name,
                                                           provider,
                                                           preferables,
                                                           strategy)
                else:
                    provider = provider[0].name

        providers[requirement_name] = provider

        if provider == package.name:
            dependencies[provider] = None
        if provider in dependencies:
            continue
        else:
            dependencies[provider] = None

    return dependencies.keys(), provided_symbols, unprovided_symbols


package_name_last_processed = None
packages_number_done = 0
packages_number_total = 0


def dependency_graph_building_status():
    """
    Reports the status of dependency graph building process.

    @return     The status tuple.
    """
    global package_name_last_processed
    global packages_number_done
    global packages_number_total
    # TODO: Fix race condition
    return ("Building edges", package_name_last_processed,
            packages_number_done, packages_number_total)


class DependencyGraphBuilder():
    """
    The builder of package dependency tree. Uses YUM as the repository
    parser. Based on repo-graph.py from yum-utils.
    """

    def __init__(self, package_name_checking_function, packages=None):
        """
        Initializes the dependency graph builder (does nothing).

        @param package_name_checking_function   The function that is used as a
                                                filter to manage packages that
                                                should be removed from the
                                                dependency graph.
        @param packages                         The list of packages names
                                                that should present in the
                                                graph with all their
                                                dependencies.
        """
        self.repository_path = None
        self.arch = None
        self.preferables = []
        self.strategy = None
        self.name_checking_function = package_name_checking_function
        self.packages = packages
        if self.packages is None or len(self.packages) == 0:
            logging.error("No package scope for the given repository has been "
                          "specified!")
        self.preferables.extend(self.packages)
        logging.debug("Initializing dependency graph builder...")

    def build_graph(self, repository_path, arch, preferables, strategy):
        """
        Builds the dependency graph of the given repository.

        @param repository_path  The path to the repository
        @param arch             The architecture to be analyzed
        @param preferables      The list of package names that should be
                                prefered in case of "have choice" problem

        @return The dependency graph in the form of hash.
        """
        self.preferables.extend(preferables)
        self.strategy = strategy
        # If the relative path is given, transform it to the absolute path,
        # because it will be written to the config file.
        repository_path = os.path.abspath(repository_path)

        check.directory_exists(repository_path)
        self.repository_path = repository_path

        # Create the unique repository ID.
        repoid = "analyzed-repo-{0}".format(os.getpid())

        config_path = self.__build_yum_config(repoid)
        self.arch = arch
        yum_base = self.__setup_yum_base(config_path, repoid, self.arch)
        graph, back_graph = self.__build_dependency_graph(yum_base)

        if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
            logging.debug("{0}".format(igraph.summary(graph)))
            logging.debug("{0}".format(graph))
            pid = os.getpid()
            suffix = re.sub('/', '_', repository_path)
            dot_file_name = "dependency_graph.{0}.{1}.dot".format(pid, suffix)
            graph.write_dot(dot_file_name)
            logging.debug("The graph was exported in DOT format to "
                          "file {0}".format(dot_file_name))

        return graph, back_graph

    def __build_yum_config(self, repoid):
        """
        Builds the YUM config that will be used for YUM initialization.

        @param repoid   The ID of repository to be analyzed.

        @return The path to generated YUM config file.
        """
        config_path = temporaries.create_temporary_file("yum.conf")
        config = ConfigParser()
        # FIXME: This config was get from my Ubuntu default yum config, maybe
        # we should somehow modify it.
        config.add_section("main")
        cache_path = temporaries.create_temporary_directory("yum.cache")
        config.set("main", "cachedir", cache_path)
        config.set("main", "keepcache", "1")
        config.set("main", "debuglevel", "2")
        log_path = temporaries.create_temporary_file("yum.log")
        config.set("main", "logfile", log_path)
        # FIXME: Is this a reason why ARM RPMs are ignored?
        config.set("main", "exactarch", "1")
        config.set("main", "obsoletes", "1")

        config.add_section(repoid)
        config.set(repoid, "name", "Analyzed repository")
        config.set(repoid, "baseurl",
                   "file://{0}".format(self.repository_path))

        with open(config_path, "w") as config_file:
            config.write(config_file)
            config_file.close()

        return config_path

    def __setup_yum_base(self, config_path, repoid, arch):
        """
        Sets the yum base up.

        @param config_path  The path to the YUM config file to be used.
        @param repoid       The ID of repository to be analyzed.
        @param arch             The architecture to be analyzed

        @return The YUM base ready for querring.
        """
        yum_base = yum.YumBase()
        yum_base.arch.setup_arch(arch)
        yum_base.doConfigSetup(config_path)

        try:
            # Disable all repositories except one that should be analyzed.
            for repo in yum_base.repos.findRepos('*'):
                if repo.id != repoid:
                    repo.disable()
                else:
                    repo.enable()

            yum_base.doRepoSetup()
            yum_base.doTsSetup()
            yum_base.doSackSetup()

        except yum.Errors.YumBaseError as error:
            logging.error("YUM error happened: {0}".format(error))
            config_file_content = open(config_path).read()
            logging.error("The following config file was "
                          "used:\n{0}".format(config_file_content))
            sys.exit(1)

        return yum_base

    def __find_package_location(self, package):
        """
        Looks for the package location inside the analyzed repository.

        @param package  The package to be found.

        @return The full path to the package file.
        """
        # FIXME: Currently YUM information about RPM location inside the given
        # repository is not accessible. That's why we mannualy search files in
        # the repository.

        package_name = _get_full_package_name(package)
        file_name = "{0}.rpm".format(package_name)

        # Check most probably paths to speed up the search.
        # This gives speed up from 10.760s to 0.711s of program run time.
        location = os.path.join(self.repository_path, self.arch, file_name)
        if os.path.exists(location):
            return location

        location = os.path.join(self.repository_path, "noarch", file_name)
        if os.path.exists(location):
            return location

        location = os.path.join(self.repository_path, file_name)
        if os.path.exists(location):
            return location

        location = None
        for root, dirs, files in os.walk(self.repository_path):
            for existing_file_name in files:
                if package_name in existing_file_name:
                    location = os.path.join(self.repository_path,
                                            existing_file_name)

        if location is None:
            raise Exception("Failed to find package {0}!".format(package))
        else:
            return location

    def __build_vertex(self, package, names, full_names, locations,
                       versions, releases, requirements, packages, yum_sack,
                       graph, back_graph):
        """
        Builds the vertex of dependency graph that corresponds to the given
        package.

        @param package          The package.
        @param names            The list of package names.
        @param full_names       The list of package full names.
        @param locations        The list of package locations.
        @param versions         The list of package versions.
        @param releases         The list of package releases.
        @param requirements     The list of package requirements.
        @param packages         The list of package objects.
        @param yum_sack         The YUM sack.
        @param graph            The forward dependency graph.
        @param back_graph       The backward dependency graph.
        """
        full_name = _get_full_package_name(package)
        logging.debug("Processing package {0} with full name "
                      "{1}".format(package, full_name))
        if self.name_checking_function is not None:
            logging.debug("Check with name function...")
            if not self.name_checking_function(full_name):
                return
        location = self.__find_package_location(package)
        # We should not include "dontuse" rpms to index at all, so delete
        # it from there:
        if "dontuse.rpm" in location:
            yum_sack.delPackage(package)
            return
        if package.name in names:
            name_id = graph.get_name_id(package.name)
            added_package = packages[name_id]
            if self.strategy is not None:
                extreme_package = _get_extreme_package(
                    [package, added_package], self.strategy)
                if extreme_package == added_package:
                    logging.debug("Already in lists.")
                    yum_sack.delPackage(package)
                else:
                    yum_sack.delPackage(added_package)
                    full_names[name_id] = full_name
                    locations[name_id] = location
                    versions[name_id] = package.version
                    releases[name_id] = package.release
                    packages[name_id] = package
                    logging.debug("Replaced with proper package.")
        else:
            i = len(names)
            graph.set_name_id(package.name, i)
            back_graph.set_name_id(package.name, i)
            names.append(package.name)
            full_names.append(full_name)
            locations.append(location)
            versions.append(package.version)
            releases.append(package.release)
            logging.debug("Package {0} requires following "
                          "symbols:".format(package.name))
            for requirement in package.requires:
                logging.debug(" * {0}".format(requirement))
            requirements.append(package.requires)
            packages.append(package)

    def __build_dependency_graph_vertices(self, yum_base):
        """
        Builds vertices of repository dependency graph.

        @param yum_base     The YUM base.
        @return             Forward and backward dependency graphs
                            (with vertices only).
        """
        graph = DependencyGraph()
        back_graph = DependencyGraph()

        yum_sack = yum_base.pkgSack

        # Remember IDs of packages in the hash.
        id_packages = {}
        i = 0
        packages = yum_sack.returnPackages()
        graph.add_vertices(len(packages))
        back_graph.add_vertices(len(packages))
        tasks = []
        names = []
        full_names = []
        locations = []
        versions = []
        releases = []
        requirements = []
        added_packages = []
        for package in packages:
            task = (package.name, package, names, full_names, locations,
                    versions, releases, requirements, added_packages, yum_sack,
                    graph, back_graph)
            tasks.append(task)
        hidden_subprocess.function_call_list(
            "Building vertices", self.__build_vertex, tasks)
        for i in range(len(names)):
            name_id = graph.get_name_id(names[i])
            if i != name_id:
                raise Exception("name id = {0} for package #{1}".format(
                    name_id, i))
        graph.vs["name"] = names
        graph.vs["full_name"] = full_names
        graph.vs["location"] = locations
        graph.vs["version"] = versions
        graph.vs["release"] = releases
        graph.vs["requirements"] = requirements
        back_graph.vs["name"] = names
        back_graph.vs["full_name"] = full_names
        back_graph.vs["location"] = locations
        back_graph.vs["version"] = versions
        back_graph.vs["release"] = releases
        back_graph.vs["requirements"] = requirements
        return graph, back_graph

    def __build_dependency_graph_edges(self, yum_base, graph, back_graph):
        """
        Builds the edges of dependency graphs.

        @param yum_base         The YUM base.
        @param graph            The forward dependency graph.
        @param back_graph       The backward dependency graph.
        @return                 Forward and backward edges.
        """
        logging.debug("Begin building edges...")
        providers = {}
        edges = []
        back_edges = []
        yum_sack = yum_base.pkgSack
        packages_scope_initial = self.packages
        package_names = [package.name for package in yum_sack.returnPackages()]
        if self.packages is None or len(self.packages) == 0:
            self.packages = package_names
            logging.error("No package scope for the given repository has been "
                          "specified!")
        packages_scope = Set(self.packages)
        for package_name in packages_scope:
            if package_name not in package_names:
                packages_scope = packages_scope - Set([package_name])
        packages_processed = Set([])
        while len(packages_processed) < len(packages_scope):
            logging.debug("Processed {0} packages from "
                          "{1}".format(len(packages_processed),
                                       len(packages_scope)))
            logging.debug("   Remaining: "
                          "{0}".format(packages_scope - packages_processed))
            for package in yum_sack.returnPackages():
                if package.name in packages_processed:
                    continue
                if package.name not in packages_scope:
                    logging.debug(" * Package {0} is still not "
                                  "processed.".format(package.name))
                    continue
                dependencies, provided, unprovided = _search_dependencies(
                    yum_sack, package, providers, self.preferables,
                    self.strategy)

                provided = graph.provided_symbols | provided
                unprovided = graph.unprovided_symbols | unprovided
                graph.provided_symbols = provided
                graph.unprovided_symbols = unprovided

                for dependency in dependencies:
                    id_begin = graph.get_name_id(package.name)
                    id_end = graph.get_name_id(dependency)
                    edges.append((id_begin, id_end))
                    back_edges.append((id_end, id_begin))
                    if (dependency not in packages_scope and
                            dependency not in packages_processed):
                        packages_scope = packages_scope | Set([dependency])
                        global packages_number_total
                        packages_number_total = len(packages_scope)
                packages_processed = packages_processed | Set([package.name])
                global package_name_last_processed
                package_name_last_processed = package.name
                global packages_number_done
                packages_number_done = len(packages_processed)
        graph.add_edges(edges)
        back_graph.add_edges(back_edges)
        providers = {}
        for package in yum_sack.returnPackages():
            for symbol in package.provides_names:
                providers[symbol] = package.name
            for file_name in package.filelist:
                providers[file_name] = package.name
        graph.symbol_providers = providers
        back_graph.symbol_providers = providers
        hidden_subprocess.function_call(
            "Inspecting file conflicts",
            self.__check_file_conflicts, yum_sack.returnPackages(),
            packages_scope_initial)

    def __check_file_conflicts(self, packages, packages_scope):
        """
        Checks file conflicts between packages.

        @param packages         The list of packages.
        @param packages_scope   The installed packages.
        """
        providers = {}
        providers_conflicts = {}
        for package in packages:
            symbols = package.filelist
            for symbol in symbols:
                provider = providers.get(symbol)
                if (provider is not None and
                        provider != package.name and
                        package.name in packages_scope):
                    if providers_conflicts.get(symbol) is None:
                        providers_conflicts[symbol] = []
                        providers_conflicts[symbol].append(providers[symbol])
                        providers_conflicts[symbol].append(package.name)
                    else:
                        providers_conflicts[symbol].append(package.name)
                providers[symbol] = package.name
        conflicts = {}
        for symbol in providers_conflicts.keys():
            conflict = tuple(sorted(providers_conflicts[symbol]))
            if conflict in conflicts.keys():
                conflicts[conflict].append(symbol)
            else:
                conflicts[conflict] = [symbol]

        scope_conflicts = {}
        for conflict in conflicts.keys():
            logging.warning(
                "Packages {0} have {1} "
                "conflicts:".format(", ".join(conflict),
                                    len(conflicts[conflict])))
            for symbol in conflicts[conflict]:
                logging.warning(" * {0}".format(symbol))
            degree = 0
            if packages_scope is not None:
                for name in conflict:
                    if name in packages_scope:
                        degree += 1
            if degree > 1:
                scope_conflicts[conflict] = conflicts[conflict]
        if len(scope_conflicts) > 0:
            for conflict in scope_conflicts:
                logging.error("Conflict between {0} is "
                              "critical.".format(", ".join(conflict)))
            # FIXME: Here the script must fail, but it was disabled due to the
            # fact that Tizen 2.4 images can be built with MIC even when some
            # such conflicts exist.

    def __build_dependency_graph(self, yum_base):
        """
        Builds the dependency graph of the repository.

        @param yum_base         The YUM base.
        @return                 Forward and backward dependency graphs.
        """
        graph, back_graph = self.__build_dependency_graph_vertices(yum_base)
        hidden_subprocess.function_call_monitor(
            self.__build_dependency_graph_edges, (yum_base, graph, back_graph),
            dependency_graph_building_status)
        return graph, back_graph
