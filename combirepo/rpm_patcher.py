#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
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
import binfmt
from kickstart_parser import KickstartFile
import repository_combiner


developer_outdir_original = None
developer_original_image = None
developer_qemu_path = None
developer_disable_patching = False


def prepare_minimal_packages_list(graphs):
    """
    Prepares the minimal list of package names that are needed to be installed
    in the chroot so that rpmrebuild can be used inside it.

    @param graphs           The list of dependency graphs of repositories.
    @return                 The list of packages.
    """
    symbols = ["useradd", "mkdir", "awk", "cpio", "make", "rpmbuild", "sed"]
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
        provider = None
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

            provider = next(iter(providers[symbol]))  # FIXME: is it correct?
        else:
            provider = next(iter(providers[symbol]))
        packages.append(provider)

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


def create_patched_packages(queue):
    """
    Patches the given package using rpmrebuild and the patching root.

    @param root             The root to be used.
    """
    root = queue.get()
    logging.debug("Chrooting to {0}".format(root))
    os.chroot(root)
    logging.debug("Chrooting to {0} done.".format(root))
    os.chdir("/")
    make_command = ["make"]
    if not hidden_subprocess.visible_mode:
        make_command.append("--silent")
    subprocess.call(make_command)
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

    def __find_platform_images(self):
        """
        Finds the platform images in the directory.

        @return                     The path to the selected images.
        """
        logging.debug("Searching in directory "
                      "{0}".format(self.images_directory))
        if not os.path.isdir(self.images_directory):
            raise Exception("{0} is not a "
                            "directory!".format(self.images_directory))
        images = files.find_fast(self.images_directory, ".*\.img$")

        return images

    def __mount_images_triplet(self, images, directory):
        """
        Mounts the images (rootfs + system-data + user) to the given
        directory.

        @param images       The list of paths to images.
        @param directory    The mount directory.
        """
        for image in images:
            if os.path.basename(image) == "rootfs.img":
                rootfs_image = image
            elif os.path.basename(image) == "system-data.img":
                system_image = image
            elif os.path.basename(image) == "user.img":
                user_image = image
            else:
                raise Exception("Unknown image name!")

        temporaries.mount_image(directory, rootfs_image)
        system_directory = os.path.join(os.path.join(directory, "opt"))
        if not os.path.isdir(system_directory):
            os.mkdir(system_directory)
        temporaries.mount_image(system_directory, system_image)
        user_directory = os.path.join(system_directory, "usr")
        if not os.path.isdir(user_directory):
            os.mkdir(user_directory)
        temporaries.mount_image(user_directory, user_image)

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

        binfmt.disable_all()
        binfmt.register(self.architecture, qemu_executable_path)

    def __install_rpmrebuild(self, queue):
        """
        Chroots to the given path and installs rpmrebuild in it.

        @param queue    The queue where the result will be put.
        """
        os.chroot(self.patching_root)
        os.chdir("/")
        os.chdir("/rpmrebuild/src")
        hidden_subprocess.call("Making the rpmrebuild.", ["make"])
        hidden_subprocess.call("Installing the rpmrebuild.",
                               ["make", "install"])
        if not check.command_exists("rpmrebuild"):
            sys.exit("Error.")
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
        images = self.__find_platform_images()
        if len(images) == 0:
            logging.error("No images were found.")
            sys.exit("Error.")
        self.patching_root = temporaries.create_temporary_directory("root")

        # For all-in-one images:
        if len(images) == 1:
            image = images[0]
            temporaries.mount_image(self.patching_root, image)
        # For 3-parts images:
        elif len(images) == 3:
            self.__mount_images_triplet(images, self.patching_root)
        else:
            raise Exception("This script is able to handle only all-in-one or "
                            "three-parted images!")

        host_arch = platform.machine()
        host_arches = self.__produce_architecture_synonyms_list(host_arch)
        if self.architecture not in host_arches:
            self.__deploy_qemu_package()

        combirepo_dir = os.path.abspath(os.path.dirname(__file__))
        rpmrebuild_file = os.path.join(combirepo_dir, 'data/rpmrebuild.tar')
        already_present_rpmrebuilds = files.find_fast(self.patching_root,
                                                      "rpmrebuild.*")
        for already_present_rpmrebuild in already_present_rpmrebuilds:
            if os.path.isdir(already_present_rpmrebuild):
                shutil.rmtree(already_present_rpmrebuild)
            elif os.path.isfile(already_present_rpmrebuild):
                os.remove(already_present_rpmrebuild)
        hidden_subprocess.call("Extracting the rpmrebuild ",
                               ["tar", "xf", rpmrebuild_file, "-C",
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
        if os.path.isdir(results_path):
            shutil.rmtree(results_path)
        os.mkdir(results_path)
        with open(makefile_path, "wb") as makefile:
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
                commands.append("s/^Release:.*/Release: {0}/g".format(release))
                for update in updates:
                    command = build_requirement_command(update)
                    commands.append(command)
                sed_command = "sed"
                for command in commands:
                    sed_command += " -e \"{0}\"".format(command)
                makefile.write("\trpmrebuild -f \'{0}\' -p -n -d "
                               "/rpmrebuild_results "
                               "{1}".format(sed_command,
                                            package_file_name))
                if logging.getLogger().getEffectiveLevel() != logging.DEBUG:
                    makefile.write(" >/dev/null 2>/dev/null")
                makefile.write(" ; \\\n")
                makefile.write("\trm -rf /home/*\n")

        if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
            subprocess.call(["cat", makefile_path])

    def _get_results(self):
        results = []
        for root in self.patching_root_clones:
            results_path = os.path.join(root, "rpmrebuild_results")
            paths = files.find_fast(results_path, ".*\.rpm")
            for path in paths:
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

    def do_tasks(self):
        """
        Creates copies of added packages in the given directories and adjusts
        their release numbers to the given values.
        """
        self.__prepare()
        global developer_disable_patching
        if developer_disable_patching:
            tasks = []
            for task in self._tasks:
                package_name, package_path, target, _, _ = task
                check.file_exists(package_path)
                tasks.append((package_name, package_path, target))
            hidden_subprocess.function_call_list(
                "Copying", shutil.copy, tasks)
        else:
            clone_tasks = []
            for i in range(repository_combiner.jobs_number):
                clone_path = temporaries.create_temporary_directory(
                    "patching_root_clone.{0}".format(i))
                shutil.rmtree(clone_path)
                self.patching_root_clones.append(clone_path)
                clone_tasks.append(
                    ("chroot #{0}".format(i),
                     ["cp", "-a", self.patching_root, clone_path]))
            hidden_subprocess.function_call_list(
                "Cloning", subprocess.call, clone_tasks)
            self._tasks.sort(key=lambda task: os.stat(task[1]).st_size)
            for i in range(repository_combiner.jobs_number):
                tasks = []
                i_task = i
                while i_task < len(self._tasks):
                    tasks.append(self._tasks[i_task])
                    i_task += repository_combiner.jobs_number

                copy_tasks = []
                directories = {}
                for task in tasks:
                    package_name, package_path, target, _, _ = task
                    copy_tasks.append((package_name, package_path,
                                       self.patching_root_clones[i]))
                    self._targets[package_name] = target
                    basename = os.path.basename(target)
                    self._package_names[basename] = package_name
                hidden_subprocess.function_call_list(
                    "Copying", shutil.copy, copy_tasks)
                self._generate_makefile(self.patching_root_clones[i], tasks)

            hidden_subprocess.function_call_monitor(
                self.__patch_packages, self._status_callback)
            results = self._get_results()
            copy_tasks = []
            for info in results:
                name, path, _ = info
                target = self._targets[name]
                copy_tasks.append((name, path, target))
            hidden_subprocess.function_call_list(
                "Copying", shutil.copy, copy_tasks)

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
        if (self.__find_platform_images() is not None and
                len(self.__find_platform_images()) > 0):
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
            repository_combiner.create_image(self.architecture, self.names,
                                             self.repositories,
                                             path, original_images_dir,
                                             [], packages)
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
