import os
import math
import random
from collections import Counter

from client import config
from logger import Logger


def calculate_entropy(data):
    if not data:
        return 0

    # shannon entropy, to see how 'random' a file is
    entropy = 0
    total_len = len(data)

    counts = Counter(data)

    for count in counts.values():
        p_x = count / total_len
        if p_x > 0:
            entropy += -p_x * math.log(p_x, 2)

    return entropy


# local IO
def local_create(filename, content):
    filepath = os.path.join(config.MONITOR_DIR, filename)
    with open(filepath, "w") as f:
        f.write(content)


def local_write(filename, content):
    filepath = os.path.join(config.MONITOR_DIR, filename)
    with open(filepath, "a") as f:
        f.write(content)
    with open(filepath, "r") as f:
        return f.read()


def local_delete(filename):
    filepath = os.path.join(config.MONITOR_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)


def is_header_modified(filepath, ext):
    # header of some file types are fixed
    # check header of specific file type
    # if the header is not the expected header, the file is modified
    expected_header = config.PROPER_HEADS.get(ext)
    if not expected_header:
        return False

    try:
        with open(filepath, "rb") as f:
            header = f.read(len(expected_header))
            if header == expected_header:
                return False
            else:
                return True
    except Exception:
        return False


def read_sampled_data(filepath):
    # will check 4 blocks of 4096 size of the file
    # random sample read, check start, mid start, mid end, end
    # combating intermittent encryption
    try:
        file_size = os.path.getsize(filepath)
        if file_size == 0:
            return b""

        with open(filepath, "rb") as f:
            # if file is smaller than sample, read all
            if file_size <= config.BLOCK_SIZE * config.NUM_BLOCKS:
                return f.read()

            sampled_data = bytearray()
            region_size = file_size // config.NUM_BLOCKS

            for i in range(config.NUM_BLOCKS):
                # allocate start and end
                region_start = i * region_size
                max_offset = max(region_start, region_start + region_size - config.BLOCK_SIZE)

                # apply random read
                offset = random.randint(region_start, max_offset)

                f.seek(offset)  # move to random place
                sampled_data.extend(f.read(config.BLOCK_SIZE))

            return bytes(sampled_data)
    except Exception as e:
        Logger.warning(f"Failed to read {filepath} | Error: {e}")
        return b""
