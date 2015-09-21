#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
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


class DependencyGraphBuilder():
    """
    The builder of package dependency tree. Uses YUM as the repository
    parser. Based on repo-graph.py from yum-utils.
    """

    def __init__(self):
        """
        Initializes the dependency graph builder (does nothing).
        """
        self.repository_path = None
        self.arch = None
        self.preferables = []
        self.strategy = None
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

    def __build_dependency_graph(self, yum_base):
        """
        Builds the dependency graph of the repository.

        @return The hash map with dependencies for each package.
        """
        dependency_graph = DependencyGraph()
        back_dependency_graph = DependencyGraph()

        providers = {}
        empty_list = []
        yum_sack = yum_base.pkgSack

        # Remember IDs of packages in the hash.
        id_packages = {}
        i = 0
        packages = yum_sack.returnPackages()
        dependency_graph.add_vertices(len(packages))
        back_dependency_graph.add_vertices(len(packages))
        names = []
        full_names = []
        locations = []
        versions = []
        releases = []
        for package in packages:
            logging.debug("Processing package {0}".format(package))
            dependency_graph.set_name_id(package.name, i)
            back_dependency_graph.set_name_id(package.name, i)
            names.append(package.name)
            full_name = _get_full_package_name(package)
            full_names.append(full_name)
            location = self.__find_package_location(package)
            # We should not include "dontuse" rpms to index at all, so delete
            # it from there:
            if "dontuse.rpm" in location:
                yum_sack.delPackage(package)
            locations.append(location)
            versions.append(package.version)
            releases.append(package.release)
            i = i + 1
        dependency_graph.vs["name"] = names
        dependency_graph.vs["full_name"] = full_names
        dependency_graph.vs["location"] = locations
        dependency_graph.vs["version"] = versions
        dependency_graph.vs["release"] = releases
        back_dependency_graph.vs["name"] = names
        back_dependency_graph.vs["full_name"] = full_names
        back_dependency_graph.vs["location"] = locations
        back_dependency_graph.vs["version"] = versions
        back_dependency_graph.vs["release"] = releases

        edges = []
        back_edges = []
        for package in yum_sack.returnPackages():
            result = _search_dependencies(yum_sack, package, providers,
                                          self.preferables, self.strategy)
            dependencies = result[0]
            provided = result[1]
            unprovided = result[2]

            provided = dependency_graph.provided_symbols | provided
            unprovided = dependency_graph.unprovided_symbols | unprovided
            dependency_graph.provided_symbols = provided
            dependency_graph.unprovided_symbols = unprovided

            for dependency in dependencies:
                id_begin = dependency_graph.get_name_id(package.name)
                id_end = dependency_graph.get_name_id(dependency)
                edges.append((id_begin, id_end))
                back_edges.append((id_end, id_begin))

        dependency_graph.add_edges(edges)
        back_dependency_graph.add_edges(back_edges)
        return dependency_graph, back_dependency_graph
