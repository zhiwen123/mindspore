# Copyright 2019 Huawei Technologies Co., Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""
Imagenet convert tool for MindRecord.
"""
import os
import time

from mindspore import log as logger
from ..common.exceptions import PathNotExistsError
from ..filewriter import FileWriter
from ..shardutils import check_filename

__all__ = ['ImageNetToMR']

class ImageNetToMR:
    """
    Class is for transformation from imagenet to MindRecord.

    Args:
        map_file (str): the map file which indicate label.
                  the map file content should like this:

                  .. code-block::

                      n02119789 1 pen
                      n02100735 2 notebook
                      n02110185 3 mouse
                      n02096294 4 orange

        image_dir (str): image directory contains n02119789, n02100735, n02110185, n02096294 dir.
        destination (str): the MindRecord file path to transform into.
        partition_number (int, optional): partition size (default=1).

    Raises:
        ValueError: If map_file, image_dir or destination is invalid.
    """
    def __init__(self, map_file, image_dir, destination, partition_number=1):
        check_filename(map_file)
        self.map_file = map_file

        check_filename(image_dir)
        self.image_dir = image_dir

        check_filename(destination)
        self.destination = destination

        if partition_number is not None:
            if not isinstance(partition_number, int):
                raise ValueError("The parameter partition_number must be int")
            self.partition_number = partition_number
        else:
            raise ValueError("The parameter partition_number must be int")

        self.writer = FileWriter(self.destination, self.partition_number)

    def _get_imagenet_as_dict(self):
        """
        Get data from imagenet as dict.

        Yields:
            data (dict of list): imagenet data list which contains dict.
        """
        if not os.path.exists(self.map_file):
            raise IOError("map file {} not exists".format(self.map_file))

        label_dict = {}
        with open(self.map_file) as fp:
            line = fp.readline()
            while line:
                labels = line.split(" ")
                label_dict[labels[1]] = labels[0]
                line = fp.readline()

        # get all the dir which are n02087046, n02094114, n02109525
        dir_paths = {}
        for item in label_dict:
            real_path = os.path.join(self.image_dir, label_dict[item])
            if not os.path.isdir(real_path):
                logger.warning("{} dir is not exist".format(real_path))
                continue
            dir_paths[item] = real_path

        if not dir_paths:
            raise PathNotExistsError("not valid image dir in {}".format(self.image_dir))

        # get the filename, label and image binary as a dict
        for label in dir_paths:
            for item in os.listdir(dir_paths[label]):
                file_name = os.path.join(dir_paths[label], item)
                if not item.endswith("JPEG") and not item.endswith("jpg"):
                    logger.warning("{} file is not suffix with JPEG/jpg, skip it.".format(file_name))
                    continue
                data = {}
                data["file_name"] = str(file_name)
                data["label"] = int(label)

                # get the image data
                image_file = open(file_name, "rb")
                image_bytes = image_file.read()
                image_file.close()
                if not image_bytes:
                    logger.warning("The image file: {} is invalid.".format(file_name))
                    continue
                data["data"] = image_bytes
                yield data

    def transform(self):
        """
        Executes transformation from imagenet to MindRecord.

        Returns:
            SUCCESS/FAILED, whether successfully written into MindRecord.
        """
        t0_total = time.time()

        imagenet_schema_json = {"label": {"type": "int64"},
                                "data": {"type": "bytes"},
                                "file_name": {"type": "string"}}

        logger.info("transformed MindRecord schema is: {}".format(imagenet_schema_json))

        # set the header size
        self.writer.set_header_size(1<<24)

        # set the page size
        self.writer.set_page_size(1<<26)

        # create the schema
        self.writer.add_schema(imagenet_schema_json, "imagenet_schema")

        # add the index
        self.writer.add_index(["label", "file_name"])

        imagenet_iter = self._get_imagenet_as_dict()
        batch_size = 256
        transform_count = 0
        while True:
            data_list = []
            try:
                for _ in range(batch_size):
                    data_list.append(imagenet_iter.__next__())
                    transform_count += 1
                self.writer.write_raw_data(data_list)
                logger.info("transformed {} record...".format(transform_count))
            except StopIteration:
                if data_list:
                    self.writer.write_raw_data(data_list)
                    logger.info("transformed {} record...".format(transform_count))
                break

        ret = self.writer.commit()

        t1_total = time.time()
        logger.info("--------------------------------------------")
        logger.info("END. Total time: {}".format(t1_total - t0_total))
        logger.info("--------------------------------------------")

        return ret
