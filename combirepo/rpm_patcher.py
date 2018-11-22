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
import sys
import platform
import shutil
import multiprocessing
import subprocess
import temporaries
import logging
import re
from sets import Set
import files
import check
import hidden_subprocess
from kickstart_parser import KickstartFile
import repository_combiner


"""
The directory where the preliminary image should be saved. If the user sets
this direcotry manually (i. e. via command line option) then the image is not
deleted at the exit from program.
"""
developer_outdir_original = None


"""
The path to ready preliminary image (i. e. already built) that user provided
via command line option.
"""
developer_original_image = None


"""
The path to the qemu package/binary that user provided via command line or
config file option.
"""
developer_qemu_path = None


"""Whether to disable RPM patching at all."""
developer_disable_patching = False


"""The path to directory with patched RPMs. """
patching_cache_path = None


"""Whether the patching cache should be dropped. """
drop_patching_cache = False


def prepare_minimal_packages_list(graphs):
    """
    Prepares the minimal list of package names that are needed to be installed
    in the chroot so that rpmrebuild can be used inside it.

    @param graphs           The list of dependency graphs of repositories.
    @return                 The list of packages.
    """
    symbols = ["useradd", "mkdir", "awk", "cpio", "make", "rpmbuild", "sed", "grep"]
    deprecated_substrings = ["mic-bootstrap", "x86", "x64"]
    providers = {}
    for symbol in symbols:
        for graph in graphs:
            if providers.get(symbol) is None:
                providers[symbol] = Set()
            names = graph.get_provider_names(symbol)
            if names is not None:
                providers[symbol] = providers[symbol] | Set(names)
                logging.debug("Got providers {0} for symbol "
                              "{1}".format(names, symbol))
                logging.debug("{0}".format(providers[symbol]))

    packages = []
    for symbol in symbols:
        if len(providers[symbol]) < 1:
            for graph in graphs:
                for key in graph.symbol_providers.keys():
                    logging.debug("{0} : {1}".format(
                        key, graph.symbol_providers[key]))
            logging.error("Failed to find symbol {0}".format(symbol))
            logging.error("size: {0}".format(len(graph.symbol_providers)))
            sys.exit("Error.")
        elif len(providers[symbol]) > 1:
            logging.debug("Analyzing symbol {0}:".format(symbol))
            for provider in providers[symbol]:
                logging.debug(" Provided by {0}".format(provider))
                for substring in deprecated_substrings:
                    if substring in provider:
                        logging.debug("   ^--- will be ignored, contains "
                                      "{0}".format(substring))
                        providers[symbol] = providers[symbol] - Set([provider])
                        logging.debug("      {0}".format(providers[symbol]))
            if len(providers[symbol]) > 1:
                logging.warning("Multiple provider names for symbol "
                                "\"{0}\":".format(symbol))
                for provider in providers[symbol]:
                    logging.warning(" * {0}".format(provider))
        if len(providers[symbol]) > 0:
            packages.append(providers[symbol].pop())

    logging.debug("Minimal packages list:")
    for package in packages:
        logging.debug(" * {0}".format(package))

    return packages


def build_requirement_command(update):
    """
    Builds the sed command that will update the requirement to the proper
    value.

    @param update                   The tuple specifying the update.
    """
    action, symbol, details = update
    relation, epoch, version, release = details
    requirement = symbol
    operator = None
    if relation is not None:
        if relation == "EQ":
            operator = "="
        elif relation == "GE":
            operator = ">="
        elif relation == "LE":
            operator = "<="
        else:
            raise Exception("Relation \"{0}\" is not implemented!".format(
                relation))
    if operator is not None:
        requirement += " {0} ".format(operator)
        if version is None:
            raise Exception("Relation \"{0}\" presents, but no version "
                            "presents!".format(relation))
        requirement += "{0}".format(version)
        if release is not None:
            requirement += "-{0}".format(release)
    logging.debug("The requirement is the following: {0}".format(requirement))
    command = None
    if action == "add":
        command = "/^Requires:/i\\Requires: {0}".format(requirement)
    elif action == "change":
        pattern = "^Requires:.*{0}.*".format(symbol)
        command = "s/{0}/Requires: {1}/g".format(pattern, requirement)
    else:
        raise Exception("Action \"{0}\" is not implemented!".format(action))
    return command


def build_subpackages_commands(path, release):
    """
    Builds the sed command that updates release of subpackages
    to the proper value.

    @param path                   Path to the package.
    @param release                Package release.
    """
    commands = []
    if not os.path.isfile(path):
        logging.debug("No such file {0}".format(path))
        return

    package = os.path.basename(path)
    package_parts = package.split('-')
    name = '-'.join(package_parts[0:-2])
    version = ''.join(package_parts[-2])
    release_pattern = "\([0-9\.\+_a-z]\+\)"
    for tag in ["Provides", "Suggests"]:
        command = "s|^{0}:\(.*\) = {1}-{2}|{0}:\\1 = {1}-{3}|g".format(
                  tag, version, release_pattern, release)
        commands.append(command)

    command = "s|^Requires:.*config({0}).* = {1}-{2}|Requires: config({0}) = {1}-{3}|g".format(
              name, version, release_pattern, release)
    commands.append(command)

    command = "s|^Requires:.*{0} = {1}-{2}|Requires: {0} = {1}-{3}|g".format(
              name, version, release_pattern, release)
    commands.append(command)

    logging.debug("Add these update commands:")
    for cmd in commands:
        logging.debug("    * {0}".format(cmd))

    return commands


def create_patched_packages(queue):
    """
    Patches the given package using rpmrebuild and the patching root.

    @param root             The root to be used.
    """
    root = queue.get()

    if not os.path.isfile(root + "/Makefile"):
        logging.info("Chroot has no jobs to perform.")
        queue.task_done()
        return

    logging.debug("Chrooting to {0}".format(root))
    make_command = ["sudo", "chroot", root, "bash", "-c",
                    """chmod a+x /usr/bin/*;
                       rm -f /var/lib/rpm/__db.*;
                       make --silent"""]
    hidden_subprocess.call("Start rpm patching", make_command)

    logging.debug("Exiting from {0}".format(root))
    queue.task_done()


class RpmPatcher():
    """
    The object of this class is used to patch RPMs so that to make them
    possible to be installed in the combined image.
    """
    def __init__(self, names, repositories, architecture, kickstart_file_path,
                 graphs):
        """
        Initializes the RPM patcher (does nothing).

        @param names                The list of repository names.
        @param repositories         The list of repositories.
        @param architecture         The architecture of the image.
        @param kickstart_file_path  The path to the working kickstart file.
        """
        self.images_directory = None
        self.names = names
        self.repositories = repositories
        self.architecture = architecture
        self.kickstart_file_path = kickstart_file_path
        global developer_qemu_path
        self.qemu_path = developer_qemu_path
        self.patching_root = None
        self.patching_root_clones = []
        self._tasks = []
        self._targets = {}
        self._package_names = {}
        self._graphs = graphs
        self.images_dict_list = {}
        self.mount_points = []

    def __produce_architecture_synonyms_list(self, architecture):
        """
        Produces the list of architecture names that are synonyms or
        compatible.

        @param architecture The architecture.
        @return             The list of compatible architectures.
        """
        if "arm64" in architecture or "aarch64" in architecture:
            return ["aarch64", "arm64", architecture]
        if "arm" in architecture:
            return ["arm", architecture]
        if "x86_64" in architecture or "86" in architecture:
            return ["x86_64", "x86", architecture]

    def __process_user_qemu_executable(self):
        """
        Processes the qemu executable specified by user, checks it and in
        case of success copies it to the directory.
        """
        qemu_executable_path = None
        if os.path.isfile(self.qemu_path):
            # FIXME: Here should be file type checking.
            if not os.path.basename(self.qemu_path).endswith(".rpm"):
                logging.info("Checking specified qemu executable "
                             "{0}...".format(self.qemu_path))
                if not check.command_exists(self.qemu_path):
                    logging.error("The specified qemu executable is not "
                                  "working.")
                    sys.exit("Error.")
                else:
                    install_directory = os.path.join(self.patching_root,
                                                     "usr/local/bin")
                    if not os.path.isdir(install_directory):
                        os.makedirs(os.path.join(install_directory))
                    qemu_name = os.path.basename(self.qemu_path)
                    install_path = os.path.join(install_directory, qemu_name)
                    shutil.copy(self.qemu_path, install_path)
                    relative_path = os.path.relpath(install_path,
                                                    self.patching_root)
                    qemu_executable_path = "/{0}".format(relative_path)

        else:
            logging.error("Specified file {0} does not exist or is not a "
                          "file!".format(qemu_path))
            sys.exit("Error.")
        return qemu_executable_path

    def __unpack_qemu_packages(self):
        """
        Looks for all qemu packages in the given list of repositories and
        unpacks them to the given directory.
        """
        initial_directory = os.getcwd()
        qemu_packages = []

        qemu_package = self.qemu_path
        if qemu_package is None:
            expression = "^qemu.*\.{0}\.rpm$".format(self.architecture)
            for repository in self.repositories:
                qemu_packages_portion = files.find_fast(repository, expression)
                qemu_packages.extend(qemu_packages_portion)
            logging.warning("The following qemu packages will be unpacked in "
                            "chroot:")
            for package in qemu_packages:
                logging.warning(" * {0}".format(package))
        else:
            qemu_packages.append(qemu_package)

        for package in qemu_packages:
            files.unrpm(package, self.patching_root)

    def __find_qemu_executable(self):
        """
        Looks for the appropriate qemu executable for the given architecture
        in the given directory.
        """

        # The synonyms for the architecture:
        arches = self.__produce_architecture_synonyms_list(self.architecture)
        executables = []
        for arch in arches:
            qemu_name = "^qemu-{0}$".format(arch)
            qemu_binfmt_name = "^qemu-{0}-binfmt$".format(arch)
            executables_portion = files.find_fast(self.patching_root,
                                                  qemu_binfmt_name)
            executables.extend(executables_portion)
            executables_portion = files.find_fast(self.patching_root,
                                                  qemu_name)
            executables.extend(executables_portion)

        logging.warning("Found several qemu executables:")
        working_executables = []
        for path in executables:
            if "bootstrap" in path:
                continue
            relative_path = os.path.relpath(path, self.patching_root)
            if check.command_exists(path):
                working_executables.append(path)
                summary = "workinig"
            else:
                summary = "not working"
            logging.warning(" * /{0} ({1})".format(relative_path, summary))

        if len(working_executables) < 1:
            logging.error("No working qemu executables found!")
            sys.exit("Error.")
        else:
            selected_path = working_executables[0]

        relative_path = os.path.relpath(selected_path, self.patching_root)
        logging.warning("The following one was selected: "
                        "/{0}".format(relative_path))
        return "/{0}".format(relative_path)

    def __deploy_qemu_package(self):
        """
        Deploys all qemu packages that can be found in the specified list of
        repositories and that have the specified architecture in the given
        directory.
        """
        qemu_executable_path = None
        if self.qemu_path is not None:
            qemu_executable_path = self.__process_user_qemu_executable()

        if qemu_executable_path is None:
            self.__unpack_qemu_packages()
            qemu_executable_path = self.__find_qemu_executable()

        combirepo_dir = os.path.abspath(os.path.dirname(__file__))
        subprocess.call(["sudo", "python2", os.path.join(combirepo_dir, "binfmt.py"),
                         "-a", self.architecture, "-q", qemu_executable_path])

    def __install_rpmrebuild(self, queue):
        """
        Chroots to the given path and installs rpmrebuild in it.

        @param queue    The queue where the result will be put.
        """
        make_command = ["sudo", "chroot", self.patching_root, "bash", "-c",
                        """chmod a+x /usr/bin/*; cd /rpmrebuild/src && make && make install"""]
        hidden_subprocess.call("Make and install the rpmrebuild.", make_command)
        queue.put(True)

    def __prepare(self):
        """
        Prepares the patching root ready for RPM patching.

        """
        global developer_disable_patching
        if developer_disable_patching:
            logging.debug("RPM patcher will not be prepared.")
            return
        graphs = self._graphs
        self.__prepare_image(graphs)
        self.__mount_root()
        host_arch = platform.machine()
        host_arches = self.__produce_architecture_synonyms_list(host_arch)
        if self.architecture not in host_arches:
            self.__deploy_qemu_package()

        combirepo_dir = os.path.abspath(os.path.dirname(__file__))
        rpmrebuild_file = os.path.join(combirepo_dir, 'data/rpmrebuild.tar')
        already_present_rpmrebuilds = files.find_fast(self.patching_root,
                                                      "rpmrebuild.*")
        for already_present_rpmrebuild in already_present_rpmrebuilds:
            hidden_subprocess.call("Remove already presented rpmrebuild.",
                                   ["sudo", "rm", "-rf", already_present_rpmrebuild])
        hidden_subprocess.call("Extracting the rpmrebuild ",
                               ["sudo", "tar", "xf", rpmrebuild_file, "-C",
                                self.patching_root])

        queue = multiprocessing.Queue()
        child = multiprocessing.Process(target=self.__install_rpmrebuild,
                                        args=(queue,))
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

    def add_task(self, package_name, package_path, location_to, release,
                 updates):
        """
        Adds a task to the RPM patcher.

        @param package_name     The name of package.
        @param package_path     The path to the marked package.
        @param location_to      The destination location.
        @param release          The release number of the corresponding
                                non-marked package.
        @param updates          The requirements updates to be performed.
        """
        self._tasks.append((package_name, package_path, location_to, release,
                            updates))

    def __patch_packages(self):
        """
        Patches all packages.
        """
        logging.debug("Creatin pool with {0} "
                      "workers.".format(repository_combiner.jobs_number))
        pool = multiprocessing.Manager().Pool(repository_combiner.jobs_number)
        queue = multiprocessing.Manager().JoinableQueue()
        for root in self.patching_root_clones:
            queue.put(root)
        for i in range(repository_combiner.jobs_number):
            result = pool.apply_async(
                create_patched_packages, (queue,))
        pool.close()
        queue.join()

    def _generate_makefile(self, root, tasks):
        """
        Generates makefile for given tasks.

        @param root             The root to be used.
        @param tasks            The list of tasks.
        """
        makefile_path = os.path.join(root, "Makefile")
        results_path = os.path.join(root, "rpmrebuild_results")

        if os.path.isfile(makefile_path):
            hidden_subprocess.call("Remove Makefile.",
                                   ["sudo", "rm", makefile_path])
        hidden_subprocess.call("Create Makefile.",
                               ["sudo", "touch", makefile_path])
        hidden_subprocess.call("Change mode of Makefile.",
                               ["sudo", "chmod", "a+rw", makefile_path])
        if os.path.isdir(results_path):
            hidden_subprocess.call("Remove results_path directory.",
                                   ["sudo", "rm", "-rf", results_path])
        hidden_subprocess.call("Create results_path directory.",
                               ["sudo", "mkdir", "-m", "777", results_path])
        with open(makefile_path, "ab") as makefile:
            makefile.write("all:")
            for task in tasks:
                package_name, _, _, _, _ = task
                makefile.write(" {0}".format(package_name))
            makefile.write("\n")
            for task in tasks:
                package_name, package_path, _, release, updates = task
                package_file_name = os.path.basename(package_path)
                makefile.write("\n")
                makefile.write("{0}: {1}\n".format(
                    package_name, package_file_name))
                commands = []
                for update in updates:
                    command = build_requirement_command(update)
                    commands.append(command)
                # skip %buildroot files in spec
                commands.append("/\.build-id/d")
                # skip basic.target.wants files in spec
                commands.append("/basic\.target\.wants/d")
                # remove -p option from %posttrans
                commands.append("s|^%posttrans -p *|%posttrans|g")
                commands_subpackages = build_subpackages_commands(package_path, release)
                commands.extend(commands_subpackages)

                sed_command = "sed"
                for command in commands:
                    sed_command += " -e \"{0}\"".format(command)
                makefile.write("\trpmrebuild -f \'{0}\' --release={1} -p -n -d "
                               "/rpmrebuild_results "
                               "{2}".format(sed_command,
                                            release,
                                            package_file_name))
                if logging.getLogger().getEffectiveLevel() != logging.DEBUG:
                    makefile.write(" >/dev/null 2>/dev/null")
                makefile.write(" ; \\\n")
            makefile.write("rm -rf /home/*\n")

        if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
            subprocess.call(["cat", makefile_path])

    def _get_results(self):
        results = []
        for root in self.patching_root_clones:
            results_path = os.path.join(root, "rpmrebuild_results")
            if not os.path.isdir(results_path):
                continue
            paths = files.find_fast(results_path, ".*\.rpm")
            for path in paths:
                if not os.path.basename(path) in self._package_names:
                    continue
                name = self._package_names[os.path.basename(path)]
                if name is None:
                    continue
                result_path = os.path.realpath(path)
                modification_time = os.path.getmtime(result_path)
                results.append((name, result_path, modification_time))
        results.sort(key=lambda tup: tup[2])
        return results

    def _status_callback(self):
        results = self._get_results()
        if len(results) > 0:
            last_name, _, _ = results[-1]
        else:
            last_name, _, _, _, _ = self._tasks[0]
        return "Patching", last_name, len(results), len(self._tasks)

    def __do_idle_tasks(self):
        """
        Does idle tasks, i. e. just copies RPMs in case when RPM patching is
        totally disabled.
        """
        tasks = []
        for task in self._tasks:
            package_name, package_path, target, _, _ = task
            check.file_exists(package_path)
            tasks.append((package_name, package_path, target))
        hidden_subprocess.function_call_list(
            "Copying w/o patching", shutil.copy, tasks)

    def __preprocess_cache(self):
        """
        Preprocesses the patching RPMs cache.
        """
        global drop_patching_cache
        if drop_patching_cache:
            global patching_cache_path
            hidden_subprocess.call("Drop patching cache", ["sudo", "rm", "-rf",
                                   patching_cache_path])
            os.makedirs(patching_cache_path)
            return

        ready_rpms = files.find_fast(patching_cache_path, ".*\.rpm")
        info_items = {}
        for rpm in ready_rpms:
            info_path = "{0}.info.txt".format(rpm)
            if os.path.isfile(info_path):
                with open(info_path, "r") as info_file:
                    lines = []
                    for line in info_file:
                        lines.append(line)
                    info_item = lines[0]
                    info_items[info_item] = rpm
        for info_item in info_items.keys():
            logging.info("Found item {0} at location "
                         "{1}".format(info_item, info_items[info_item]))

        copy_tasks = []
        tasks_undone = []
        for i_task in range(len(self._tasks)):
            task = self._tasks[i_task]
            name, path, destination, release, updates = task
            info = "{0}".format((name, path, release, updates))
            logging.info("Searching for {0}".format(info))
            if_cached = False
            for key in info_items.keys():
                if key == info:
                    cached_package_path = info_items[key]
                    logging.info("Found already patched RPM at "
                                 "{0}".format(cached_package_path))
                    copy_tasks.append((name, cached_package_path,
                                       destination))
                    if_cached = True
                    break
            if not if_cached:
                tasks_undone.append(task)
        self._tasks = tasks_undone

        if len(copy_tasks) > 0:
            hidden_subprocess.function_call_list(
                "Copying from cache", shutil.copy, copy_tasks)

    def __clone_chroots(self):
        """
        Clones patching chroot to several clones.
        """
        clone_tasks = []
        for i in range(repository_combiner.jobs_number):
            clone_path = temporaries.create_temporary_directory(
                "patching_root_clone.{0}".format(i))
            shutil.rmtree(clone_path)
            self.patching_root_clones.append(clone_path)
            clone_tasks.append(
                ("chroot #{0}".format(i),
                 ["sudo", "cp", "-a", self.patching_root, clone_path]))
        hidden_subprocess.function_call_list(
            "Cloning chroot", subprocess.call, clone_tasks)

    def __deploy_packages(self):
        """
        Deploys packages to chroot clones and generates makefiles for them.
        """
        self._tasks.sort(key=lambda task: os.stat(task[1]).st_size)
        for i in range(repository_combiner.jobs_number):
            tasks = []
            i_task = i
            while i_task < len(self._tasks):
                tasks.append(self._tasks[i_task])
                i_task += repository_combiner.jobs_number

            if len(tasks) == 0:
                continue

            directories = {}
            for task in tasks:
                package_name, package_path, target, _, _ = task
                self._targets[package_name] = target
                basename = os.path.basename(target)
                self._package_names[basename] = package_name
                hidden_subprocess.call("Copying to patcher",
                                       ["sudo", "cp", package_path,
                                       self.patching_root_clones[i]])
            self._generate_makefile(self.patching_root_clones[i], tasks)

    def __postprocess_cache(self):
        """
        Postprocesses the patching RPMs cache.
        """
        results = self._get_results()
        for result in results:
            name, path, _ = result
            global patching_cache_path
            destination_path = os.path.join(
                patching_cache_path, os.path.basename(path))
            matching_task = None
            for task in self._tasks:
                if task[0] == name:
                    name, marked_rpm_path, _, release, updates = task
                    matching_task = (name, marked_rpm_path, release, updates)
            if matching_task is None:
                raise Exception("Cannot match task for {0}".format(name))
            info_path = "{0}.info.txt".format(destination_path)
            info = "{0}".format(matching_task)
            with open(info_path, "wb") as info_file:
                info_file.write(info)
            hidden_subprocess.call("Copying to cache",
                                   ["sudo", "cp", path, destination_path])

    def __process_results(self):
        """
        Processes final results of patcher.
        """
        results = self._get_results()
        for info in results:
            name, path, _ = info
            target = self._targets[name]
            hidden_subprocess.call("Copying to repo",
                                   ["sudo", "cp", path, target])

    def __mount_root(self):
        """
        Mount preliminary images.
        """
        kickstart_file = KickstartFile(self.kickstart_file_path)
        self.images_dict_list = kickstart_file.get_images_mount_points()
        self.patching_root = temporaries.mount_firmware(self.images_directory,
                                                        self.images_dict_list)

    def __umount_root(self):
        """
        Umount preliminary images.
        """
        if not self.images_dict_list:
            logging.debug("No mount points to umount")
            return
        for images_dict in reversed(self.images_dict_list):
            mount_path = os.path.join(self.patching_root,
                                      images_dict["mount_point"])
            temporaries.umount_image(mount_path)

    def __mount_fs(self):
        """
        Mount system directories required for patching.
        """
        self.mount_points = ["sys", "proc", "dev", "dev/pts", "dev/null",
                             "/dev/mqueue", "/dev/shm"]
        for root in self.patching_root_clones:
            for mount_point in self.mount_points:
                temporaries.mount_bind(root, mount_point)

    def __umount_fs(self):
        """
        Umount system directories required for patching.
        """
        for root in self.patching_root_clones:
            for mount_point in reversed(self.mount_points):
                temporaries.umount_image(os.path.join(root, mount_point))

    def __use_cached_root_or_prepare(self):
        """
        Tries to find cached root and uses it in case it exists and prepares
        it otherwise.
        """
        image_info = "{0}".format((self.names, self.repositories,
                                   self.architecture,
                                   os.path.basename(self.kickstart_file_path)))
        cached_images_info_paths = files.find_fast(
            patching_cache_path, ".*preliminary_image.info.txt")
        matching_images_path = None
        for info_path in cached_images_info_paths:
            cached_images_path = info_path.replace(".info.txt", "")
            if not os.path.isdir(cached_images_path):
                logging.error("Directory {0} not "
                              "found!".format(cached_images_path))
                continue
            lines = []
            with open(info_path, "r") as info_file:
                for line in info_file:
                    lines.append(line)
            if lines[0] == image_info:
                matching_images_path = cached_images_path
                break
        if matching_images_path is not None:
            self.patching_root = matching_images_path
            logging.info("Found already prepared patching root: "
                         "{0}".format(matching_images_path))
        else:
            self.__prepare()
            cached_chroot_path = os.path.join(
            patching_cache_path, os.path.basename(
                self.patching_root) + "preliminary_image")
            hidden_subprocess.call(
                "Saving chroot to cache",
                ["sudo", "cp", "-Z", "-P", "-a", self.patching_root,
                cached_chroot_path])
            info_path = cached_chroot_path + ".info.txt"
            with open(info_path, "wb") as info_file:
                info_file.write(image_info)

    def do_tasks(self):
        """
        Creates copies of added packages in the given directories and adjusts
        their release numbers to the given values.
        """
        global developer_disable_patching
        if developer_disable_patching:
            self.__do_idle_tasks()
        else:
            self.__preprocess_cache()
            if len(self._tasks) > 0:
                self.__use_cached_root_or_prepare()
                self.__clone_chroots()
                self.__umount_root()
                self.__mount_fs()
                self.__deploy_packages()
                hidden_subprocess.function_call_monitor(
                    self.__patch_packages, (), self._status_callback)
                self.__postprocess_cache()
                self.__process_results()
                self.__umount_fs()

    def __prepare_image(self, graphs):
        """
        Prepares the image needed for the RPM patcher.

        @param graphs           The list of dependency graphs of repositories.
        @return                 The directory with preliminary images.
        """
        original_images_dir = None
        global developer_original_image
        global developer_outdir_original
        if developer_outdir_original is None:
            path = temporaries.create_temporary_directory("preliminary-image")
            developer_outdir_original = path
        self.images_directory = developer_outdir_original
        if not os.path.isdir(developer_outdir_original):
            os.makedirs(developer_outdir_original)
        images = files.find_fast(self.images_directory, ".*\.img$")
        if (images is not None and len(images) > 0):
            return

        if developer_original_image is None:
            if developer_outdir_original is None:
                directory = temporaries.create_temporary_directory("orig")
                developer_outdir_original = directory
            original_images_dir = developer_outdir_original
            path = temporaries.create_temporary_file("mod.ks")
            shutil.copy(self.kickstart_file_path, path)
            kickstart_file = KickstartFile(path)
            kickstart_file.comment_all_groups()
            logging.debug("Repositories: {0}".format(self.repositories))
            packages = prepare_minimal_packages_list(graphs)
            repository_combiner.create_image(
                self.architecture, self.names, self.repositories, path,
                ["--outdir", original_images_dir], packages)
        else:
            if os.path.isdir(developer_original_image):
                original_images_dir = developer_original_image
            elif os.path.isfile(developer_original_image):
                original_images_dir = os.path.dirname(developer_original_image)
            else:
                logging.error("Given {0} is not a file or a "
                              "directory.".format(developer_original_image))
                sys.exit("Error.")
        self.images_directory = original_images_dir
