#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import logging
import os
import sys
from iniparse import ConfigParser
import yum
import cStringIO
import igraph
from temporaries import create_temporary_file, create_temporary_directory


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
    output = cStringIO.StringIO()
    output.write("{0}".format(package))
    file_name = str(output.getvalue())
    output.close()

    return file_name


def _search_dependencies(yum_sack, package, providers):
    """
    Searches the dependencies of the given package in the repository

    @param yum_sack     The YUM sack used to search packages.
    @param package      The package which dependencies are searched.
    @param providers    Cached RPM symbols providers

    @return             List of package names on which the given package
                        depends on
    """
    logging.debug("Processing package: {0}".format(package))
    # Hash of already built dependencies.
    # FIXME: This hash is used just as a set, not as a hash.
    dependencies = {}

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
                logging.error("Nothing provides {0} required by {1}".
                              format(requirement_name, package.name))
                continue
            else:
                if len(provider) != 1:
                    logging.error("Have choice for {0}:".
                                  format(requirement_name))
                    for p in provider:
                        logging.error(" * {0}".format(p))
                        # FIXME: In case if we want sabe have-choice
                        # information in the resulting graph, we need to
                        # modify this behaviour
                provider = provider[0].name

        providers[requirement_name] = provider

        if provider == package.name:
            dependencies[provider] = None
        if provider in dependencies:
            continue
        else:
            dependencies[provider] = None

    return dependencies.keys()


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
        logging.debug("Initializing dependency graph builder...")

    def build_graph(self, repository_path, arch):
        """
        Builds the dependency graph of the given repository.

        @param repository_path  The path to the repository
        @param arch             The architecture to be analyzed

        @return The dependency graph in the form of hash.
        """
        # If the relative path is given, transform it to the absolute path,
        # because it will be written to the config file.
        repository_path = os.path.abspath(repository_path)

        if not os.path.isdir(repository_path):
            raise Exception("Directory {0} does not exist!".format(
                            repository_path))
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
            dot_file_name = "dependency_graph.{0}.dot".format(os.getpid())
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
        config_path = create_temporary_file("yum.conf")
        config = ConfigParser()
        # FIXME: This config was get from my Ubuntu default yum config, maybe
        # we should somehow modify it.
        config.add_section("main")
        cache_path = create_temporary_directory("yum.cache")
        config.set("main", "cachedir", cache_path)
        config.set("main", "keepcache", "1")
        config.set("main", "debuglevel", "2")
        log_path = create_temporary_file("yum.log")
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

        file_name = "{0}.rpm".format(_get_full_package_name(package))

        # Check most probably paths to speed up the search.
        # This gives speed up from 10.760s to 0.711s of program run time.
        location = os.path.join(self.repository_path, self.arch, file_name)
        if os.path.exists(location):
            return location

        location = os.path.join(self.repository_path, file_name)
        if os.path.exists(location):
            return location

        location = None
        for root, dirs, files in os.walk(self.repository_path):
            if file_name in files:
                location = os.path.join(self.repository_path, file_name)

        if location is None:
            logging.error("Failed to find package {0}!".format(package))
            return None
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
        for package in packages:
            dependency_graph.set_name_id(package.name, i)
            back_dependency_graph.set_name_id(package.name, i)
            names.append(package.name)
            full_name = _get_full_package_name(package)
            full_names.append(full_name)
            location = self.__find_package_location(package)
            locations.append(location)
            i = i + 1
        dependency_graph.vs["name"] = names
        dependency_graph.vs["full_name"] = full_names
        dependency_graph.vs["location"] = locations
        back_dependency_graph.vs["name"] = names
        back_dependency_graph.vs["full_name"] = full_names
        back_dependency_graph.vs["location"] = locations

        edges = []
        back_edges = []
        for package in yum_sack.returnPackages():
            dependencies = _search_dependencies(yum_sack, package, providers)

            for dependency in dependencies:
                id_begin = dependency_graph.get_name_id(package.name)
                id_end = dependency_graph.get_name_id(dependency)
                edges.append((id_begin, id_end))
                back_edges.append((id_end, id_begin))

        dependency_graph.add_edges(edges)
        back_dependency_graph.add_edges(back_edges)
        return dependency_graph, back_dependency_graph
