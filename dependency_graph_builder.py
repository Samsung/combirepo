#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import logging
import os
import sys
from iniparse import ConfigParser
import yum
from temporaries import create_temporary_file, create_temporary_directory


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
        yum_base = self.__setup_yum_base(config_path, repoid, arch)
        dependency_hash = self.__build_dependency_hash(yum_base)
        return dependency_hash

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
        config.set(repoid, "name", "Sanitized repository")
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

    def __build_dependency_hash(self, yum_base):
        """
        Builds the dependency graph of the repository.

        @return The hash map with dependencies for each package.
        """
        # FIXME: For now the resulting graph consists of nodes that contain
        # only names of packages. But to modularize the package, we also need
        # to save relative paths of files.
        dependency_hash = {}
        providers = {}
        empty_list = []
        yum_sack = yum_base.pkgSack

        for package in yum_sack.returnPackages():
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
                        provider = provider[0].name

                providers[requirement_name] = provider

                if provider == package.name:
                    dependencies[provider] = None
                if provider in dependencies:
                    continue
                else:
                    dependencies[provider] = None

            dependency_hash[package.name] = dependencies.keys()

        return dependency_hash
