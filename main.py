import sys
from loguru import logger
from exr import EXRSequence
from pathlib import Path


if __name__ == '__main__':
    if len(sys.argv) != 2:
        logger.error(f'Arguments invalid: {sys.argv}')
        raise ValueError()

    folder_path = Path(sys.argv[1])
    if not folder_path.is_dir() or not folder_path.exists():
        logger.error(f'Folder invalid: {folder_path}')
        raise ValueError()

    exr_seq = EXRSequence(folder_path)
    exr_seq.separate()
