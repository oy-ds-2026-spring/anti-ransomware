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


# vector lock: add 1 to the clock when local writes
def increment_clock(filename):
    with config.CLOCK_LOCK:
        if filename not in config.FILE_CLOCKS:
            config.FILE_CLOCKS[filename] = {}
        current_val = config.FILE_CLOCKS[filename].get(config.CLIENT_ID, 0)
        config.FILE_CLOCKS[filename][config.CLIENT_ID] = current_val + 1
        return config.FILE_CLOCKS[filename].copy()
        # config.VECTOR_CLOCK[config.CLIENT_ID] = (
        #     config.VECTOR_CLOCK.get(config.CLIENT_ID, 0) + 1
        # )
        # return config.VECTOR_CLOCK.copy()


# merge clock ( max(clocks) + 1 ) when receiving sync message
def merge_clock(filename, incoming_clock):
    with config.CLOCK_LOCK:
        if filename not in config.FILE_CLOCKS:
            config.FILE_CLOCKS[filename] = {}
        local_clock = config.FILE_CLOCKS[filename]
        
        # 
        for node, time_val in incoming_clock.items():
            local_clock[node] = max(local_clock.get(node, 0), time_val)
            # config.VECTOR_CLOCK[node] = max(config.VECTOR_CLOCK.get(node, 0), time_val)
            
        # merge indicate local receive and processes the event
        # time should move forward
        # config.VECTOR_CLOCK[config.CLIENT_ID] = (
        #     config.VECTOR_CLOCK.get(config.CLIENT_ID, 0) + 1
        # )
        # return config.VECTOR_CLOCK.copy()
        local_clock[config.CLIENT_ID] = local_clock.get(config.CLIENT_ID, 0) + 1
        return local_clock.copy()


def get_clock(filename):
    with config.CLOCK_LOCK:
        return config.FILE_CLOCKS.get(filename, {}).copy()
    # with config.CLOCK_LOCK:
    #     return config.VECTOR_CLOCK.copy()


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
                max_offset = max(
                    region_start, region_start + region_size - config.BLOCK_SIZE
                )

                # apply random read
                offset = random.randint(region_start, max_offset)

                f.seek(offset)  # move to random place
                sampled_data.extend(f.read(config.BLOCK_SIZE))

            return bytes(sampled_data)
    except Exception as e:
        Logger.warning(f"Failed to read {filepath} | Error: {e}")
        return b""


def detect_conflict(local_clock, incoming_clock):
    # detects if two vector clocks are conflicted (concurrent)
    # is concurrent if a !>= b, and b !>= a
    local_is_greater_or_equal = True
    incoming_is_greater_or_equal = True

    all_keys = set(local_clock.keys()).union(set(incoming_clock.keys()))
    for k in all_keys:
        lv = local_clock.get(k, 0)
        iv = incoming_clock.get(k, 0)
        if lv < iv:
            local_is_greater_or_equal = False
        if iv < lv:
            incoming_is_greater_or_equal = False

    # conflict
    if not local_is_greater_or_equal and not incoming_is_greater_or_equal:
        return True
    return False
