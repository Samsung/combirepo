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

import sys
import subprocess
import tempfile
import atexit
import shutil
import os
import logging
import files

debug_mode = False
default_directory = None

def __umask_temporary_file(path, mode):
    """
    Changes mode of temporary file or directory:

    @param path    Path to the file.
    @param mode    New file mode.
    """
    umask = os.umask(0)
    os.chmod(path, mode)
    os.umask(umask)


def create_temporary_file(file_suffix):
    """
    Creates temporary file in tmpfs, named as follows:

    default_directory/combirepo.<random>.<suffix>

    @param file_suffix      The suffix of temporary file.

    @return                 The path to created temporary file.
    """
    global default_directory
    if not os.path.isdir(default_directory):
        os.makedirs(default_directory)
        __umask_temporary_file(default_directory, 0777)
    file_descriptor, path = tempfile.mkstemp(prefix='combirepo.',
                                             suffix="." + file_suffix,
                                             dir=default_directory)
    os.close(file_descriptor)  # This helps to avoid the file descriptor leak.
    __umask_temporary_file(path, 0666)
    if not debug_mode:
        atexit.register(os.remove, path)  # It will be removed at exit.
    logging.debug("Created temporary file {0}".format(path))
    return path


def create_temporary_directory(directory_suffix):
    """
    Creates temporary directory in tmpfs, named as follows:

    default_directory/combirepo.<random>.<suffix>

    @param file_suffix      The suffix of temporary directory.

    @return                 The path to created temporary directory.
    """
    global default_directory
    if not os.path.isdir(default_directory):
        os.makedirs(default_directory)
        __umask_temporary_file(default_directory, 0777)
    path = tempfile.mkdtemp(prefix='combirepo.',
                            suffix="." + directory_suffix,
                            dir=default_directory)
    __umask_temporary_file(path, 0777)
    if not debug_mode:
        atexit.register(shutil.rmtree, path)  # It will be removed at exit.
    logging.debug("Created temporary file {0}".format(path))
    return path


def mount_image(directory, image_path):
    """
    Creates temporary mount point of the given image in the given directory.

    default_directory/combirepo.<random>.<suffix>

    and mounts the image to it.

    @param directory        The path to the directory.
    @param image_path       The path to the image to be mounted.

    @return                 The path to created temporary directory.
    """
    value = subprocess.call(["sudo", "mount", "-o", "rw,loop", image_path, directory])
    if value != 0:
        logging.error("Failed to mount image.")
        sys.exit("Error.")
    if not debug_mode:
        atexit.register(subprocess.call, ["sudo", "umount", "-l", directory])
    logging.debug("Mounted image {0} to {1}".format(image_path, directory))
    return


def umount_image(directory):
    """
    Umount temporary mount point of the given directory.

    default_directory/combirepo.<random>.<suffix>.

    @param directory        The path to the directory.
    """
    if os.path.ismount(directory):
        value = subprocess.call(["sudo", "umount", "-l", directory])
        if value != 0:
            logging.error("Failed to umount image.")
            sys.exit("Error.")
        logging.debug("Umounted {0}".format(directory))
    return


def __find_platform_images(images_directory):
    """
    Finds the platform images in the directory.

    images_directory            The directory with images.

    @return                     The path to the selected images.
    """
    logging.debug("Searching in directory "
                  "{0}".format(images_directory))
    if not os.path.isdir(images_directory):
        raise Exception("{0} is not a "
                        "directory!".format(images_directory))
    images = files.find_fast(images_directory, ".*\.img$")

    return images


def __mount_images(images, directory, images_dict_list):
    """
    Mounts the images (rootfs, system-data, user and etc) to the given
    directory.

    @param images       The list of paths to images.
    @param directory    The mount directory.
    """
    for images_dict in images_dict_list:
        for image in images:
            img_name = os.path.basename(image)
            if images_dict['name'] == img_name and img_name != "modules.img":
                mount_point = images_dict['mount_point']
                mount_dir = os.path.join(os.path.join(directory, mount_point))
                if not os.path.isdir(mount_dir):
                    os.makedirs(mount_dir)
                mount_image(mount_dir, image)


def mount_firmware(firmware_path, images_dict_list):
    """
    Creates temporary mount points of the given firmware.

    @param firmware_path    The path to the firmware to be mounted.

    @return                 The path to created temporary directory.
    """
    images = __find_platform_images(firmware_path)
    if len(images) == 0:
        logging.error("No images were found.")
        sys.exit("Error.")
    root = create_temporary_directory("root")
    __mount_images(images, root, images_dict_list)

    return root


def mount_bind(root, mount_point):
    """
    Bind mount directory.

    @param root           The path to the root.
    @param mount_point    Directory to mount.

    """
    logging.debug("Bind mount {0}".format(mount_point))
    value = subprocess.call(["sudo", "mount", "--bind", "/" + mount_point,
                             os.path.join(root, mount_point)])
    if value != 0:
        logging.error("Failed to mount {0}.".format(mount_point))
        sys.exit("Error.")
