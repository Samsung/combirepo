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
import shutil
import tempfile
import logging
import re
import configparser
from urllib2 import urlopen
# Combirepo modules:
import files
import check
from directory_downloader import download_directory


update_repositories = None


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
            global update_repositories
            if (update_repositories is not None and
                    (url in update_repositories or
                        "all" in update_repositories)):
                shutil.rmtree(os.path.dirname(config_path))
                logging.info("Repository for URL {0} will be "
                             "updated!".format(url))
            else:
                self._repositories.append(repository)

        for repository in self._repositories:
            logging.debug("Found repository: {0}".format(repository))

    def prepare(self, url, authenticator, packages_list = None):
        """
        Prepares the local copy of the repository that is specified at the
        given url.

        @param url              The URL of the repository.
        @param authenticator    The encoded user:password string for download
                                server.
        """
        logging.debug("Starting preparation of repo from URL {0}".format(url))
        if url is None:
            return None
        if os.path.isdir(url):
            return url
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
            if repository_found is None:
                self._repositories.append(repository)
            else:
                self._repositories[i_repository] = repository
            parser = configparser.SafeConfigParser()
            parser.add_section('repository')
            parser.set('repository', 'url', url)
            parser.set('repository', 'status', 'empty')
            with open(os.path.join(repository["path"],
                      ".repository.conf"), 'wb') as repository_config:
                parser.write(repository_config)
            # Download the repository (if we are here, then it's not ready)
            logging.debug("Downloading directory {0}".format(url))
            download_directory(repository["url"],
                               repository["path"],
                               self._name_checking_function, authenticator,
                               packages_list)
            self.remove_duplicates(repository["path"])
            repository["status"] = "ready"
            parser.set('repository', 'status', 'ready')
            with open(os.path.join(repository["path"],
                      ".repository.conf"), 'wb') as repository_config:
                parser.write(repository_config)

            return repository["path"]

        raise Exception("Impossible happened.")

    def remove_duplicates(self, repository_path):
        rpm_list = []
        for root, dirs, files in os.walk(repository_path):
            for file in files:
                if file.endswith(".rpm"):
                    rpm_list.append(file)
        for pkg1 in rpm_list:
            for pkg2 in rpm_list:
                if pkg1 != pkg2:
                    split1 = pkg1.rsplit('.', 3)
                    split2 = pkg2.rsplit('.', 3)
                    if split1[0] == split2[0]:
                        logging.debug("Select between {0} and {1}".format(pkg1, pkg2))
                        if split1[1] > split2[1]:
                            rpm_list.remove(pkg2)
                            rpm_path = os.path.join(repository_path, split2[2], pkg2)
                            if os.path.exists(rpm_path):
                                logging.debug("Removing {0}".format(pkg2))
                                os.remove(rpm_path)
                        else:
                            rpm_list.remove(pkg1)
                            rpm_path = os.path.join(repository_path, split1[2], pkg1)
                            if os.path.exists(rpm_path):
                                logging.debug("Removing {0}".format(pkg1))
                                os.remove(rpm_path)
                            break
