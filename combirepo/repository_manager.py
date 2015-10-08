#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import tempfile
import logging
import re
import configparser
from urllib2 import urlopen
# Combirepo modules:
import files
import check
from directory_downloader import download_directory


class RepositoryManager():
    """
    Simple repository downloader.
    """
    def __init__(self, cache_directory, name_checking_function):
        """
        Initializes the repository downloader.

        @param cache_directory          The combirepo cache directory.
        @param name_checking_function   The function that checks URLs to be
                                        downloaded.
        """
        check.directory_exists(cache_directory)
        self._cache_directory = cache_directory
        self._repositories = []
        self._name_checking_function = name_checking_function

        config_paths = files.find_fast(self._cache_directory,
                                       ".repository.conf")
        for config_path in config_paths:
            parser = configparser.SafeConfigParser()
            parser.read(config_path)
            if not parser.has_section("repository"):
                logging.error("Repository config {0} does not contain "
                              "[repository] section!".format(config_path))
                continue
            if not parser.has_option("repository", "url"):
                logging.error("Repository config {0} does not contain "
                              "option \"url\" in section "
                              "[repository]!".format(config_path))
                continue
            url = parser.get("repository", "url")
            if not parser.has_option("repository", "status"):
                logging.error("Repository config {0} does not contain "
                              "option \"status\" in section "
                              "[repository]!".format(config_path))
                status = "unknown"
            else:
                status = parser.get("repository", "status")
            repository = {}
            repository["url"] = url
            repository["path"] = os.path.dirname(config_path)
            repository["status"] = status
            self._repositories.append(repository)

        for repository in self._repositories:
            logging.debug("Found repository: {0}".format(repository))

    def prepare(self, url, authenticator):
        """
        Prepares the local copy of the repository that is specified at the
        given url.

        @param url              The URL of the repository.
        @param authenticator    The encoded user:password string for download
                                server.
        """
        logging.debug("Starting preparation of repo from URL {0}".format(url))
        if url is None:
            raise Exception("url is None")
        repository_found = None
        i_repository = 0
        for repository in self._repositories:
            if repository["url"] == url:
                repository_found = repository
                logging.debug("Repository {0} is found in local copy at "
                              "{1}".format(url, repository["path"]))
                break
            i_repository = i_repository + 1
        if repository_found is None:
            repository = {}
            path_created = tempfile.mkdtemp(suffix="repository",
                                            prefix="combirepo",
                                            dir=self._cache_directory)
            repository["path"] = path_created
            repository["url"] = url
            repository["status"] = "empty"
        else:
            repository = repository_found

        if repository["status"] == "ready":
            logging.debug("The repository is downloaded and ready to "
                          "be used.")
            return repository["path"]
        elif repository["status"] == "empty":
            # Download the repository (if we are here, then it's not ready)
            logging.debug("Downloading directory {0}".format(url))
            download_directory(repository["url"],
                               repository["path"],
                               self._name_checking_function, authenticator)
            repository["status"] = "ready"
            if repository_found is None:
                self._repositories.append(repository)
            else:
                self._repositories[i_repository] = repository
            parser = configparser.SafeConfigParser()
            parser.add_section('repository')
            parser.set('repository', 'url', url)
            parser.set('repository', 'status', 'ready')
            with open(os.path.join(repository["path"],
                      ".repository.conf"), 'wb') as repository_config:
                parser.write(repository_config)

            return repository["path"]

        raise Exception("Impossible happened.")
