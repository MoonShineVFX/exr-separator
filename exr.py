import OpenEXR
import Imath
from pathlib import Path
from loguru import logger
from concurrent.futures import ProcessPoolExecutor
from time import perf_counter


class EXRChannelInfo:
    def __init__(self, channel_name: str, channel_type: Imath.Channel):
        self._name: str = channel_name
        self._type: Imath.Channel = channel_type
        self._labels: [str] = []

    def get_name(self):
        return self._name

    def get_type(self):
        return self._type

    def get_pixel_type(self):
        return self._type.type

    def get_labels(self):
        return self._labels

    def get_target_channels(self):
        return ['R', 'G', 'B', 'A'][:len(self.get_labels())]

    @staticmethod
    def compare_labels(element: str):
        ele = element[-1].lower()
        compare_values = {
            'r': 0, 'g': 1, 'b': 2, 'a': 3,
            'x': 0, 'y': 1, 'z': 2, 'w': 3
        }
        return compare_values[ele]

    def add_label(self, label):
        self._labels.append(label)
        self._labels.sort(key=self.compare_labels)

    def is_color(self):
        return self.get_name() == 'C'

    def is_depth(self):
        return self.get_name() == 'Z'

    def is_valid(self):
        label_count = len(self.get_labels())
        if self.is_depth():
            if label_count == 1:
                return True
            return False
        return label_count in (3, 4)

    def get_pixels_data(self, exr: OpenEXR.InputFile) -> dict:
        pixels_data = {}
        for i, target_channel in enumerate(self.get_target_channels()):
            label_index = i
            if self.is_depth():
                label_index = 0
            pixels_data[target_channel] = exr.channel(self.get_labels()[label_index], self.get_pixel_type())
        return pixels_data

    def __repr__(self):
        return f'EXR ChannelInfo [{self.get_name()}] - type: {self.get_type()} labels: {self.get_labels()}'


class EXRSequence:
    color_channel_labels = ('R', 'G', 'B', 'A')
    depth_channel_labels = ('Z', )

    def __init__(self, folder_path: Path):
        logger.info(f'Create from "{folder_path}"')
        self._folder_path: Path = folder_path
        self._exr_files: [Path] = self._get_files()
        self._header: dict = self._get_header()
        self._channels_info: {str: EXRChannelInfo} = self._get_channels_info()

    def _get_files(self) -> [Path]:
        exr_files = list(self._folder_path.glob('*.exr'))
        logger.info(f'{len(exr_files)} files found')
        return exr_files

    def _get_header(self) -> dict:
        exr_file = OpenEXR.InputFile(str(self._exr_files[0]))
        logger.debug('EXR Sequence header:')
        header = exr_file.header()
        for k, v in header.items():
            logger.debug(f'{k}: {v}')
        exr_file.close()
        return header

    def _get_channels_info(self) -> {str: EXRChannelInfo}:
        channels_info = {}

        # create channels
        for channel_label, channel_type in self._header['channels'].items():
            channel_name = None
            if channel_label in self.color_channel_labels:
                channel_name = 'C'
            elif channel_label in self.depth_channel_labels:
                channel_name = 'Z'
            elif '.' in channel_label:
                channel_name = channel_label.split('.')[0]
            else:
                logger.warning(f'Unrecognized channel: {channel_label}')
                continue

            if channel_name not in channels_info:
                channels_info[channel_name] = EXRChannelInfo(channel_name, channel_type)

            this_channel_info = channels_info[channel_name]
            if channel_type != this_channel_info.get_type():
                logger.warning(f"Channel type doesn't matched: {this_channel_info} <-> {channel_label}")
            this_channel_info.add_label(channel_label)

        # filter channels
        to_remove_channel_names = []
        for channel_name, channel_info in channels_info.items():
            if not channel_info.is_valid():
                to_remove_channel_names.append(channel_name)
                logger.warning(f"Channel [{channel_name}]'s labels is invalid: {channel_info.get_labels()}")
        for to_remove_channel_name in to_remove_channel_names:
            del channels_info[to_remove_channel_name]

        logger.info(f'Parsed channels: {", ".join(channels_info.keys())}')

        return channels_info

    def separate(self):
        logger.info('Start separation')
        start_time = perf_counter()

        # add args
        process_args = []
        for exr_file in self._exr_files:
            for channel_name in self._channels_info.keys():
                process_args.append((self, exr_file, channel_name))

        # process
        with ProcessPoolExecutor() as executor:
            executor.map(self.save_channel, process_args)

        # finish report
        end_time = perf_counter()
        logger.info(f'Finish separation ({end_time - start_time:.02f}s)')

    @staticmethod
    def append_channel_name_to_filename(file: Path, channel_name: str):
        filename_chars = [char for char in file.stem]
        frame_number = []

        while True:
            if filename_chars[-1].isdecimal():
                frame_number.insert(0, filename_chars.pop())
                continue
            break

        while True:
            if not filename_chars[-1].isalpha():
                frame_number.insert(0, filename_chars.pop())
                continue
            break

        return f'{"".join(filename_chars)}.{channel_name}{"".join(frame_number)}{file.suffix}'

    @staticmethod
    def clean_header(header: dict):
        to_remove_keys = [
            'image:crop', 'image:window', 'renderMemory', 'renderTime', 'space:world',
            'worldToCamera', 'worldToNDC',
            'order'
        ]
        for to_remove_key in to_remove_keys:
            if to_remove_key in header:
                del header[to_remove_key]

    @staticmethod
    def save_channel(arg):
        exr_sequence: EXRSequence = arg[0]
        exr_file: Path = arg[1]
        channel_name: str = arg[2]

        if channel_name not in exr_sequence._channels_info.keys():
            logger.error(f'No channel name "{channel_name}" found ({exr_sequence._channels_info})')
            return

        logger.info(f'Separate [{channel_name}]: {exr_file}')

        logger.debug(f'Source: {exr_file}')
        source_exr = OpenEXR.InputFile(str(exr_file))
        channel_info = exr_sequence._channels_info[channel_name]

        # make header
        header = source_exr.header()
        exr_sequence.clean_header(header)

        header['channels'] = {}
        for c in channel_info.get_target_channels():
            header['channels'][c] = channel_info.get_type()

        # make folder
        target_folder = exr_sequence._folder_path.joinpath(channel_name)
        logger.debug(f'Make folder: {target_folder}')
        target_folder.mkdir(parents=True, exist_ok=True)
        target_exr_file = target_folder.joinpath(exr_sequence.append_channel_name_to_filename(exr_file, channel_name))

        # make exr
        logger.debug(f'Write file: {target_exr_file}')
        target_exr = OpenEXR.OutputFile(str(target_exr_file), header)
        pixels_data = channel_info.get_pixels_data(source_exr)
        target_exr.writePixels(pixels_data)

        target_exr.close()
        source_exr.close()

        logger.info(f'File saved: {str(target_exr_file)}')
